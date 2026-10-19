"""Offline ablations. Mock dense ordering is a contract test, not quality evidence."""
import hashlib
import json
import math
import tempfile
import time
from pathlib import Path
from .story_retriever import StoryRetriever, read_channel
from .style_retriever import TOPICS


def metrics(ids, gold, k):
    ids, relevant = ids[:k], set(gold)
    found = relevant.intersection(ids)
    reciprocal = next((1 / rank for rank, ident in enumerate(ids, 1) if ident in relevant), 0)
    dcg = sum(1 / math.log2(rank + 1) for rank, ident in enumerate(ids, 1) if ident in relevant)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return {'recall_at_k': len(found) / len(relevant) if relevant else None,
            'mrr': reciprocal if relevant else None, 'ndcg_at_k': dcg / ideal if ideal else None,
            'irrelevant_injection': bool(ids) if not relevant else None}


def evaluate(dataset, k=4, data_dir=None, dense=None, dense_label='deterministic_mock'):
    rows = list(read_channel('lore', data_dir)) + list(read_channel('style', data_dir)) if data_dir else dataset['records']
    cases = dataset['cases']
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_record_id')
    known = {r['id'] for r in rows}
    if any(not set(case['gold']) <= known for case in cases):
        raise ValueError('unknown_gold_id')
    report = dict(synthetic=dataset.get('synthetic', False), k=k, dense_provider=dense_label, strategies={},
                  dense_fallback=False, note='Dense-only has no sparse fallback in evaluation.')
    # Explicit mock: uses provided semantic keywords, never gold labels.
    def mock_dense(channel, query, documents, limit):
        ranked = []
        for row in documents:
            score = sum(word in query for word in row.get('keywords', []))
            if score:
                ranked.append((row['id'], score))
        return [(ident, 1 / score) for ident, score in sorted(ranked, key=lambda h: (-h[1], h[0]))[:limit]]
    with tempfile.TemporaryDirectory() as temporary:
        directory = data_dir or temporary
        if not data_dir:
            for channel, name in (('lore', 'story_knowledge'), ('style', 'dialogue_examples')):
                Path(directory, name + '.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n'
                    for r in rows if r['evidence_type'] == channel), encoding='utf-8')
        for strategy in ('legacy', 'sparse', 'dense', 'hybrid'):
            results = []
            for case in cases:
                started = time.perf_counter()
                if strategy == 'legacy':
                    # Frozen pre-upgrade scoring, including its unrelated-result behavior.
                    terms = {w for source, target in TOPICS if any(w in case['query'] for w in source) for w in target}
                    pool = [r for r in rows if r.get('character') == case['character']]
                    ranked = sorted(pool, key=lambda r: (sum(w in r['text'] for w in terms),
                        hashlib.sha256((case['query'] + r['text']).encode()).digest()), reverse=True)
                    ids = [r['id'] for r in ranked[:k]]
                else:
                    hits, trace = StoryRetriever(case['channel'], root=directory, dense=dense or mock_dense).retrieve(
                        case['character'], case['query'], k, strategy, case.get('filters'), allow_fallback=False)
                    ids = [r['id'] for r in hits]
                results.append(dict(case=case['id'], hit_ids=ids, trace=trace if strategy != 'legacy' else None,
                                    latency_ms=(time.perf_counter() - started) * 1000,
                                    **metrics(ids, case['gold'], k)))
            aggregate = {}
            for key in ('recall_at_k', 'mrr', 'ndcg_at_k', 'irrelevant_injection', 'latency_ms'):
                values = [r[key] for r in results if r[key] is not None]
                aggregate[key] = sum(values) / len(values) if values else None
            report['strategies'][strategy] = dict(aggregate=aggregate, cases=results)
    return report
