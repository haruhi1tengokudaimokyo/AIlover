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
import hashlib
import json
from functools import lru_cache

from django.conf import settings

TABLE_PREFIX = 'style_'

# 透明的中日词组对应，只用于本地词法排序，不等同于语义嵌入。
TOPICS = (
    (('吃', '饭', '料理', '厨房', '饿'), ('料理', '食', 'ご飯', 'お腹', '台所', '吃饭', '做饭', '厨房', '肚子', '饿')),
    (('累', '工作', '休息', '睡'), ('疲', '仕事', '休', '寝', '眠', '累', '工作', '休息', '睡')),
    (('喜欢', '可爱', '约会', '爱你'), ('好き', '可愛', 'デート', '恋', '喜欢', '可爱', '约会')),
    (('钱', '工资', '买', '贵'), ('お金', '給料', '買', '高い', '钱', '工资', '买', '贵')),
    (('朋友', '菖蒲', '绯华', '麦'), ('友達', '菖蒲', '緋華', 'むぎ')),
    (('你好', '早上', '晚上', '回来'), ('おはよう', 'こんにちは', 'こんばんは', 'お帰り', '你好', '早上', '晚上', '回来')),
)


@lru_cache(maxsize=16)
def _load_samples(path_string, modified):
    import json
    samples, seen = [], set()
    for raw in Path(path_string).read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(raw)
            text = row.get('text', '').strip()
        except (ValueError, AttributeError):
            continue
        if 12 <= len(text) <= 120 and text not in seen:
            seen.add(text)
            samples.append((text, row.get('file', '')))
    return tuple(samples)


def _retrieve_local(slug, query, k):
    path = _lines_path(slug)
    if not path.exists():
        return []
    samples = _load_samples(str(path), path.stat().st_mtime_ns)
    terms = {word for source, target in TOPICS if any(word in query for word in source) for word in target}
    def score(item):
        text, scene = item
        matches = sum(word in text for word in terms)
        # 对相同消息结果稳定，无匹配时分散到整个语料而非永远取开头。
        tie = hashlib.sha256((query + text).encode('utf-8')).digest()
        return (matches, tie)
    ranked = sorted(samples, key=score, reverse=True)
    ranked = [item for item in ranked if score(item)[0] > 0]
    chosen, scenes, remaining = [], set(), []
    for text, scene in ranked:
        if scene not in scenes:
            chosen.append(text)
            scenes.add(scene)
        else:
            remaining.append(text)
        if len(chosen) >= k:
            break
    return (chosen + remaining)[:k]


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
        embedding=CustomEmbeddings(),
        connection=db,
        table_name=TABLE_PREFIX + slug,
        mode='overwrite',
    )
    return vector_db._table.count_rows()


def _retrieve_vector(slug: str, query: str, k: int = 5):
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


def retrieve(slug: str, query: str, k: int = 5):
    """检索不可用时降级，避免风格参考阻断主对话。"""
    import logging
    import json
    import re
    if not slug or not re.fullmatch(r'[a-zA-Z0-9_-]+', slug) or not query.strip() or k <= 0:
        return []
    try:
        lines = _retrieve_vector(slug, query, k)
        if lines:
            return lines
    except Exception:
        logging.getLogger(__name__).warning('角色 %s 的向量检索失败，使用本地词法检索', slug)
    return _retrieve_local(slug, query, k)
