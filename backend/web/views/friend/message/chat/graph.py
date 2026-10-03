import os
from pathlib import Path
from typing import TypedDict, Annotated, Sequence

from django.conf import settings
from django.utils.timezone import now, localtime
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.constants import START, END
from langgraph.graph import add_messages, StateGraph
from langgraph.prebuilt import ToolNode


def _build_tools():
    @tool
    def get_time() -> str:
        """当需要查询精确时间时，调用此函数，返回格式为: [年-月-日 时:分:秒]"""
        return localtime(now()).strftime('%Y-%m-%d %H:%M:%S')

    tools = [get_time]

    # 知识库存在时才挂载检索工具，避免 lancedb 表缺失导致报错
    kb_dir = Path(settings.BASE_DIR) / 'web/documents/lancedb_storage'
    if kb_dir.exists():
        @tool
        def search_knowledge_base(query: str) -> str:
            """当用户查询阿里云百炼平台的相关信息时，调用此函数，输入为要查询的问题，输出为查询结果"""
            try:
                import lancedb
                from langchain_community.vectorstores import LanceDB
                from web.documents.utils.custom_embeddings import CustomEmbeddings
                db = lancedb.connect(str(kb_dir))
                vector_db = LanceDB(
                    connection=db,
                    embedding=CustomEmbeddings(),
                    table_name='my_knowledge_base',
                )
                docs = vector_db.similarity_search(query, k=3)
                context = '\n\n'.join([f'内容片段：{i + 1}\n{doc.page_content}' for i, doc in enumerate(docs)])
                return f'从知识库中找到以下信息：\n\n{context}\n'
            except Exception as e:
                return f'知识库暂时不可用：{e}'
        tools.append(search_knowledge_base)

    return tools


class ChatGraph:
    @staticmethod
    def create_app():
        tools = _build_tools()

        llm = ChatOpenAI(
            model=os.getenv('MODEL', 'deepseek-v3.2'),
            openai_api_key=os.getenv('API_KEY'),
            openai_api_base=os.getenv('API_BASE'),
            streaming=True,
            # 角色扮演场景：略高的温度让回复更有「人味」，
            # 频率惩罚抑制复读与套话（原来默认全为 0，容易复读）
            temperature=float(os.getenv('LLM_TEMPERATURE', '0.95')),
            top_p=float(os.getenv('LLM_TOP_P', '0.9')),
            frequency_penalty=float(os.getenv('LLM_FREQUENCY_PENALTY', '0.4')),
            presence_penalty=float(os.getenv('LLM_PRESENCE_PENALTY', '0.3')),
            model_kwargs={
                "stream_options": {
                    "include_usage": True,  # 输出token消耗数量
                }
            }
        ).bind_tools(tools)

        class AgentState(TypedDict):
            messages: Annotated[Sequence[BaseMessage], add_messages]

        def model_call(state: AgentState) -> AgentState:
            res = llm.invoke(state['messages'])
            return {'messages': [res]}

        def should_continue(state: AgentState) -> str:
            last_message = state['messages'][-1]
            if last_message.tool_calls:
                return 'tools'
            return 'end'

        tool_node = ToolNode(tools)

        graph = StateGraph(AgentState)
        graph.add_node('agent', model_call)
        graph.add_node('tools', tool_node)

        graph.add_edge(START, 'agent')
        graph.add_conditional_edges(
            'agent',
            should_continue,
            {
                'tools': 'tools',
                'end': END,
            }
        )
        graph.add_edge('tools', 'agent')

        return graph.compile()
