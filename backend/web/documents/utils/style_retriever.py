# -*- coding: utf-8 -*-
"""
角色台词风格检索（RAG，无需微调）。

数据：web/documents/character_lines/<slug>.jsonl（每行 {"text","voice","file"}，
      由 scripts/build_character_data.py 从游戏剧本提取并清洗）。
索引：LanceDB 表 style_<slug>，由 `python manage.py build_style_index` 构建。
检索：聊天时按用户消息做向量相似度检索，取回最相关的若干原作台词，
      注入系统提示词作为语气/口癖参考（见 chat.py）。
"""
from pathlib import Path

from django.conf import settings

TABLE_PREFIX = 'style_'


def _lines_path(slug: str) -> Path:
    return Path(settings.BASE_DIR) / 'web/documents/character_lines' / f'{slug}.jsonl'


def _db_path() -> Path:
    # 向量索引是可写的运行时数据，放 DATA_DIR（exe 模式下是 exe 旁边的 data/）
    data_dir = getattr(settings, 'DATA_DIR', None) or Path(settings.BASE_DIR)
    return Path(data_dir) / 'lancedb_style'


def table_exists(slug: str) -> bool:
    db_dir = _db_path()
    if not db_dir.exists():
        return False
    import lancedb
    db = lancedb.connect(str(db_dir))
    return TABLE_PREFIX + slug in db.table_names()


def build_index(slug: str, batch_size: int = 10) -> int:
    """嵌入并写入角色的台词向量索引，返回写入条数。"""
    import json

    import lancedb
    from langchain_community.vectorstores import LanceDB
    from langchain_core.documents import Document

    from web.documents.utils.custom_embeddings import CustomEmbeddings

    path = _lines_path(slug)
    if not path.exists():
        raise FileNotFoundError(f'台词库不存在: {path}')

    docs = []
    for line in path.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        docs.append(Document(
            page_content=row['text'],
            metadata={'voice': row.get('voice') or '', 'file': row.get('file', '')},
        ))

    db = lancedb.connect(str(_db_path()))
    vector_db = LanceDB.from_documents(
        documents=docs,
        embeding=CustomEmbeddings(),
        connection=db,
        table_name=TABLE_PREFIX + slug,
        mode='overwrite',
    )
    return vector_db._table.count_rows()


def retrieve(slug: str, query: str, k: int = 5):
    """按用户消息检索最相关的原作台词，返回文本列表。索引不存在时返回空列表。"""
    if not slug or not query.strip() or not table_exists(slug):
        return []
    import lancedb
    from langchain_community.vectorstores import LanceDB

    from web.documents.utils.custom_embeddings import CustomEmbeddings

    db = lancedb.connect(str(_db_path()))
    vector_db = LanceDB(
        connection=db,
        embedding=CustomEmbeddings(),
        table_name=TABLE_PREFIX + slug,
    )
    docs = vector_db.similarity_search(query, k=k)
    # 去重且避免整段过长
    seen, out = set(), []
    for d in docs:
        t = d.page_content.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t[:120])
    return out
