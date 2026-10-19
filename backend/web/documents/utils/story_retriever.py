"""Independent lore/style channels, CJK lexical fallback, optional LanceDB RRF."""
import hashlib
import json
import math
import os
import re
import time
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from .style_retriever import TOPICS
from .story_pipeline import ALIASES


def bundle_path():
    return Path(os.getenv('STORY_DATA_DIR') or Path(settings.DATA_DIR) / 'story_data')


def terms(text):
    text = text.casefold()
    result = set(re.findall(r'[a-z0-9_]{2,}', text))
    for run in re.findall(r'[\u3040-\u30ff\u3400-\u9fff]+', text):
        if len(run) == 1:
            result.add(run)  # explicit one-character query fallback
        else:
            result.update(run[i:i + 2] for i in range(len(run) - 1))
    return result


def expanded_terms(query):
    result = terms(query)
    for source, target in TOPICS:
        if any(word in query for word in source):
            for word in target:
                result.update(terms(word))
    for alias, slug in ALIASES.items():
        if alias in query:
            for other, character in ALIASES.items():
                if character == slug:
                    result.update(terms(other))
    return result


@lru_cache(maxsize=8)
def load_rows(path, mtime, size):
    rows, ids = [], set()
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                or not isinstance(row.get('text'), str)
                or not isinstance(row.get('keywords', []), list)
                or any(not isinstance(word, str) for word in row.get('keywords', []))):
            raise ValueError('invalid_evidence_schema')
        if row.get('id') and row.get('text'):
            if row['id'] in ids:
                raise ValueError('duplicate_evidence_id')
            ids.add(row['id'])
            rows.append(row)
    return tuple(rows)


def read_channel(channel, root=None):
    path = Path(root or bundle_path()) / ('story_knowledge.jsonl' if channel == 'lore' else 'dialogue_examples.jsonl')
    if not path.is_file():
        return ()
    stat = path.stat()
    return load_rows(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def lexical_index(path, mtime, size):
    """CJK posting lists, rebuilt only when the source bundle changes."""
    index = {}
    for row in load_rows(path, mtime, size):
        text = row['text'] + ' ' + ' '.join(row.get('keywords', []))
        indexed = terms(text) | set(re.findall(r'[\u3040-\u30ff\u3400-\u9fff]', text))
        for term in indexed:
            index.setdefault(term, set()).add(row['id'])
    return index


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def dense_path():
    return Path(settings.DATA_DIR) / 'lancedb_story'


def table_name(channel, rows):
    configuration = json.dumps([os.getenv('EMBEDDING_MODEL', 'text-embedding-v4'),
        os.getenv('EMBEDDING_DIMENSIONS', '1024'), os.getenv('EMBEDDING_API_BASE') or os.getenv('API_BASE')], ensure_ascii=False)
    provider = hashlib.sha256(configuration.encode()).hexdigest()[:12]
    return f'{channel}_{fingerprint(rows)}_{provider}'


def build_dense(channel, root=None, batch_size=32):
    import lancedb
    from .custom_embeddings import CustomEmbeddings
    rows = read_channel(channel, root)
    if not rows:
        return 0
    embedder, data = CustomEmbeddings(), []
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        vectors = embedder.embed_documents([r['text'] for r in batch])
        if len(vectors) != len(batch):
            raise ValueError('embedding_batch_size_mismatch')
        data.extend(dict(id=r['id'], vector=v) for r, v in zip(batch, vectors))
    # Content-addressed table: queries cannot accidentally use a stale evidence build.
    db = lancedb.connect(str(dense_path()))
    db.create_table(table_name(channel, rows), data=data, mode='overwrite')
    return len(data)


def dense_search(channel, query, rows, limit):
    if not dense_path().is_dir():
        return []
    import lancedb
    from .custom_embeddings import CustomEmbeddings
    db = lancedb.connect(str(dense_path()))
    name = table_name(channel, rows)
    if name not in db.table_names():
        return []
    vector = CustomEmbeddings().embed_query(query)
    hits = db.open_table(name).search(vector).limit(limit).to_list()
    # Distance threshold must be calibrated for the configured embedding provider.
    threshold = float(os.getenv('STORY_DENSE_MAX_DISTANCE', '0.8'))
    return [(hit['id'], float(hit['_distance'])) for hit in hits
            if math.isfinite(float(hit['_distance'])) and float(hit['_distance']) <= threshold]


class StoryRetriever:
    def __init__(self, channel, root=None, dense=None, reranker=None):
        if channel not in ('lore', 'style'):
            raise ValueError('invalid_channel')
        self.channel, self.root = channel, root
        self.dense = dense if dense is not None else dense_search
        self.reranker = reranker

    def retrieve(self, character, query, k=4, strategy='hybrid', filters=None, recent='', allow_fallback=True):
        started = time.perf_counter()
        trace = dict(channel=self.channel, strategy=strategy, status='ok', hit_ids=[])
        if strategy not in ('sparse', 'dense', 'hybrid', 'off'):
            raise ValueError('invalid_strategy')
        if strategy == 'off' or not query.strip() or k <= 0:
            return [], trace
        filters = filters or {}
        try:
            rows = read_channel(self.channel, self.root)
        except (OSError, ValueError, TypeError):
            trace.update(status='degraded', reason='bundle_unreadable', latency_ms=round((time.perf_counter() - started) * 1000, 3))
            return [], trace
        def allowed(row):
            characters = row.get('characters') or [row.get('character')]
            if character not in characters:
                return False
            # Unknown route/scene is not evidence for a requested known route/scene.
            for key in ('route_id', 'scene_id', 'source_file'):
                if filters.get(key) is not None and row.get(key) != filters[key]:
                    return False
            if filters.get('route_id') is None and row.get('route_id') is not None:
                return False
            return not row.get('branch')  # no inferred branch traversal
        candidates = {r['id']: r for r in rows if allowed(r)}
        wanted = expanded_terms(query[:2000])
        contextual = expanded_terms(recent[-1000:])
        path = Path(self.root or bundle_path()) / ('story_knowledge.jsonl' if self.channel == 'lore' else 'dialogue_examples.jsonl')
        sparse = []
        if rows:
            stat = path.stat()
            index = lexical_index(str(path), stat.st_mtime_ns, stat.st_size)
            scores = {}
            for term in wanted:
                for ident in index.get(term, ()):
                    if ident in candidates:
                        scores[ident] = scores.get(ident, 0) + 1 / max(1, len(wanted))
            for term in contextual:
                for ident in index.get(term, ()):
                    if ident in scores:
                        scores[ident] += .05
            sparse = list(scores.items())
        sparse.sort(key=lambda item: (-item[1], item[0]))
        limit = min(64, max(16, k * 4))
        sparse = sparse[:limit]
        dense = []
        if strategy in ('dense', 'hybrid'):
            if self.dense is not dense_search or os.getenv('STORY_DENSE_ENABLED', 'false').lower() == 'true':
                try:
                    dense = [(ident, score) for ident, score in self.dense(self.channel, query, rows, limit)
                             if ident in candidates]
                    if not dense:
                        trace.update(status='degraded', reason='dense_empty_or_missing')
                except Exception:
                    trace.update(status='degraded', reason='dense_unavailable')
            else:
                trace.update(status='degraded', reason='dense_disabled')
        if not rows:
            trace.update(status='degraded', reason='bundle_missing_or_empty')
        routes = []
        if strategy in ('sparse', 'hybrid') or (strategy == 'dense' and not dense and allow_fallback):
            routes.append(('sparse', sparse))
        if dense:
            routes.append(('dense', dense))
        fused, methods = {}, {}
        for method, hits in routes:
            seen_ids = set()
            for rank, (ident, score) in enumerate(hits, 1):
                if ident in seen_ids:
                    continue
                seen_ids.add(ident)
                fused[ident] = fused.get(ident, 0) + 1 / (60 + rank)
                methods.setdefault(ident, []).append(method)
        ranked = sorted(fused, key=lambda ident: (-fused[ident], ident))
        results, seen = [], set()
        for ident in ranked:
            row = candidates[ident]
            signature = row['text'].strip()
            if signature in seen:
                continue
            seen.add(signature)
            results.append(dict(row, retrieval_method='+'.join(methods[ident]), score=fused[ident]))
        if self.reranker:
            try:
                reordered = self.reranker(query, list(results))
                permitted = {r['id']: r for r in results}
                if len(reordered) != len(permitted) or set(r['id'] for r in reordered) != set(permitted):
                    raise ValueError('reranker_changed_candidates')
                results = [permitted[r['id']] for r in reordered]
            except Exception:
                trace.update(status='degraded', reason='reranker_failed')
        results = results[:min(k, 16)]
        trace.update(hit_ids=[r['id'] for r in results], latency_ms=round((time.perf_counter() - started) * 1000, 3))
        return results, trace


class LoreRetriever(StoryRetriever):
    def __init__(self, **kwargs):
        super().__init__('lore', **kwargs)


class StyleRetriever(StoryRetriever):
    def __init__(self, **kwargs):
        super().__init__('style', **kwargs)
