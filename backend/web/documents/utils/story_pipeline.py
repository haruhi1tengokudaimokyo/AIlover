"""Conservative KAG parsing and reproducible, local-only evidence bundles.

No inferred plot facts: lore is accepted only from a reviewed sidecar.
"""
import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

ALIASES = {'緋華': 'hika', '佐藤緋華': 'hika', '绯华': 'hika',
           '菖蒲': 'ayame', '藤ヶ丘菖蒲': 'ayame',
           'むぎ': 'mugi', '麦': 'mugi', '小麦': 'mugi'}
# The alias set is part of parsed records; old caches lack mugi's identity.
PARSER_VERSION = 2
CONTROL = {'if', 'else', 'elsif', 'endif', 'eval', 'c', 'r', 'hh',
           'layopt', 'jump', 'call', 'return', 'icHeart'}
TAG = re.compile(r'\[([^\]]+)\]')
SPAN = re.compile(r'\[>>\](.*?)\[<<\]', re.S)


def decode_source(path):
    raw = Path(path).read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16'
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeError:
            pass
    raise ValueError('unsupported_encoding')


def parse_script(path, root):
    """Locations are physical lines; context never crosses label/branch boundaries."""
    source = Path(path).relative_to(root).as_posix()
    text, encoding = decode_source(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    rows, audit = [], []
    speaker, voice, label = None, None, None
    branch, segment = [], 0
    pending, start = None, None
    def emit(body, first, last):
        nonlocal voice
        raw_text = body.strip()
        if not raw_text:
            return
        tags = TAG.findall(raw_text)
        visible = TAG.sub('', raw_text).strip()
        loc = {'line_start': first, 'line_end': last}
        ordinal = sum(r['source_location']['line_start'] == first for r in rows)
        ident = hashlib.sha256(f'{source}:{first}:{last}:{ordinal}'.encode()).hexdigest()[:24]
        uncertainties = []
        if speaker is None:
            uncertainties.append('unknown_speaker')
        elif speaker not in ALIASES and speaker != '地':
            uncertainties.append('unmapped_speaker')
        if tags:
            uncertainties.append('inline_markup')
        if branch:
            uncertainties.append('conditional_branch')
        if any('unknown_control' == a.get('reason') and a['line'] <= first for a in audit):
            uncertainties.append('unresolved_control_flow')
        rows.append(dict(id=ident, source_file=source, source_location=loc,
                         source_sha256=digest, encoding=encoding, sequence=len(rows),
                         speaker=speaker, character=ALIASES.get(speaker), text=visible,
                         raw_text=raw_text, voice_id=voice, scene_id=f'{source}#{label}' if label else None,
                         route_id=None, label=label, branch=list(branch), segment=segment,
                         evidence_type='narration' if speaker == '地' else 'dialogue',
                         emotion=None, uncertainties=uncertainties))
        voice = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if pending is not None:
            pending += '\n' + line
            if '[<<]' in line:
                emit(pending.split('[<<]', 1)[0], start, number)
                pending = None
            continue
        if not line or line.startswith(';'):
            continue
        if line.startswith('*'):
            label = line[1:].split('|', 1)[0].strip()
            segment += 1
            speaker, voice = None, None
            continue
        command = line[1:].split()[0] if line.startswith('@') else None
        if command in ('if', 'elsif', 'else', 'endif') or re.match(r'\[(?:if|elsif|else|endif)(?:\s|\])', line):
            name = command or line[1:].split(']', 1)[0].split()[0]
            segment += 1
            speaker, voice = None, None
            if name == 'if':
                branch.append(line)
            elif name == 'endif':
                if branch:
                    branch.pop()
                else:
                    audit.append(dict(source_file=source, line=number, reason='unbalanced_branch'))
            elif branch:
                branch[-1] = line
            else:
                audit.append(dict(source_file=source, line=number, reason='unbalanced_branch'))
            continue
        if line.startswith('@'):
            # These engine commands may alter control flow; do not infer their effects.
            if re.search(r'jump|call|return|select|choice', command or '', re.I):
                segment += 1
                speaker, voice = None, None
                audit.append(dict(source_file=source, line=number, reason='unknown_control'))
            continue
        match = TAG.match(line)
        if match and not line.startswith('[>>]'):
            tag = match[1]
            name = tag.split()[0]
            if name in CONTROL or not re.fullmatch(r'[^\s=\[\]>/]+', name) or (' ' in tag and 'vo=' not in tag):
                segment += 1
                speaker, voice = None, None
                audit.append(dict(source_file=source, line=number, reason='unknown_tag'))
                continue
            speaker = name
            v = re.search(r'\bvo=([\w-]+)', tag)
            voice = v[1] if v else None
            line = line[match.end():]
        matches = list(SPAN.finditer(line))
        if matches:
            for m in matches:
                emit(m[1], number, number)
        elif '[>>]' in line:
            pending, start = line.split('[>>]', 1)[1], number
        elif line and not line.startswith('['):
            emit(line, number, number)
    if pending is not None:
        audit.append(dict(source_file=source, line=start, reason='unterminated_dialogue'))
    if branch:
        audit.append(dict(source_file=source, reason='unclosed_branch'))
    for index, row in enumerate(rows):
        nearby = rows[max(0, index - 2):index] + rows[index + 1:index + 3]
        row['context'] = [dict(id=r['id'], speaker=r['speaker'], text=r['text'],
                               evidence_type=r['evidence_type']) for r in nearby if r['segment'] == row['segment']]
    return rows, audit


def build_bundle(root, output, review=None, voice_root=None, usable=None, previous=None, character_filters=None):
    """Publish immutable build directories. Review sidecar is never modified."""
    root, output = Path(root), Path(output)
    if output.exists():
        raise ValueError('output_exists: choose a new build directory')
    files = sorted(root.rglob('*.ks'))
    if not files:
        raise ValueError('no_scenario_files')
    review_bytes = Path(review).read_bytes() if review else None
    sidecar = json.loads(review_bytes.decode('utf-8')) if review_bytes is not None else {}
    review_sha256 = hashlib.sha256(review_bytes).hexdigest() if review_bytes is not None else None
    all_rows, issues, coverage, cache = [], [], [], []
    old = {}
    if previous:
        cache_path = Path(previous) / 'parse_cache.jsonl'
        if cache_path.is_file():
            old = {entry['source_file']: entry for entry in
                   (json.loads(line) for line in cache_path.read_text(encoding='utf-8').splitlines())}
    reused = 0
    for path in files:
        try:
            source = path.relative_to(root).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            prior = old.get(source)
            if prior and prior.get('parser_version') == PARSER_VERSION and prior.get('source_sha256') == digest:
                rows, audit = prior['rows'], prior['issues']
                reused += 1
            else:
                rows, audit = parse_script(path, root)
            # Serialize before applying sidecar corrections so cached parser output stays raw.
            cache.append(json.dumps(dict(source_file=source, source_sha256=digest, parser_version=PARSER_VERSION,
                                         rows=rows, issues=audit), ensure_ascii=False) + '\n')
            all_rows.extend(rows)
            issues.extend(audit)
            coverage.append(dict(source_file=path.relative_to(root).as_posix(), records=len(rows)))
        except (UnicodeError, ValueError):
            issues.append(dict(source_file=path.relative_to(root).as_posix(), reason='decode_failed'))
    ids = {row['id']: row for row in all_rows}
    for ident, patch in sidecar.get('corrections', {}).items():
        if ident not in ids or patch.get('source_sha256') != ids[ident]['source_sha256']:
            issues.append(dict(id=ident, reason='stale_correction'))
            continue
        for key in ('speaker', 'character', 'text', 'route_id', 'emotion', 'scene_id'):
            if key in patch:
                ids[ident][key] = patch[key]
        if 'speaker' in patch:
            ids[ident]['evidence_type'] = 'narration' if patch['speaker'] == '地' else 'dialogue'
            if 'character' not in patch:
                ids[ident]['character'] = ALIASES.get(patch['speaker'])
        ids[ident]['reviewed'] = True
        ids[ident]['review_sha256'] = review_sha256
    # Rehydrate context after corrections, keeping original boundary decisions.
    for row in all_rows:
        row['context'] = [dict(id=c['id'], speaker=ids[c['id']]['speaker'],
                               text=ids[c['id']]['text'], evidence_type=ids[c['id']]['evidence_type'])
                          for c in row['context']]
    examples, voices = [], []
    for row in all_rows:
        if row['voice_id']:
            audio = Path(voice_root) / (row['voice_id'] + '.opus') if voice_root else None
            voices.append(dict(id=row['id'], voice_id=row['voice_id'],
                               audio_path=str(audio) if audio and audio.is_file() else None,
                               source_file=row['source_file'], source_location=row['source_location']))
        character_filter = (character_filters or {}).get(row['character'])
        if (row['character'] and row['evidence_type'] == 'dialogue'
                and (usable is None or usable(row['text']))
                and (character_filter is None or character_filter(row))):
            sample = dict(row, evidence_type='style', style_labels=[], reviewed=row.get('reviewed', False))
            sample['context'] = [c for c in sample['context'] if (usable is None or usable(c['text']))
                                 and (character_filter is None or character_filter(c))]
            examples.append(sample)
    lore = []
    for fact in sidecar.get('lore', []):
        refs = fact.get('source_ids', [])
        if (fact.get('reviewed') is True and fact.get('id') and fact.get('text') and refs
                and all(ref in ids for ref in refs)
                and all(fact.get('source_hashes', {}).get(ref) == ids[ref]['source_sha256'] for ref in refs)):
            source = ids[refs[0]]
            lore.append(dict(fact, evidence_type='lore', source_file=source['source_file'],
                             source_location=source['source_location'], review_sha256=review_sha256))
        else:
            issues.append(dict(id=fact.get('id'), reason='unverified_lore'))
    duplicates = sum(n - 1 for n in Counter((r['speaker'], r['text']) for r in all_rows).values())
    report = dict(schema_version=1, review_sha256=review_sha256, source_files=len(files), parsed_records=len(all_rows),
                  dialogue_examples=len(examples), verified_lore=len(lore), voice_records=len(voices),
                  duplicates=duplicates, reused_source_files=reused, uncertain_records=sum(bool(r['uncertainties']) for r in all_rows),
                  missing_fields={key: sum(r.get(key) is None for r in all_rows)
                                  for key in ('speaker', 'character', 'voice_id', 'route_id', 'scene_id', 'emotion')},
                  missing_audio=sum(r['audio_path'] is None for r in voices),
                  source_coverage=coverage, issues=issues)
    destination = output
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='.story-partial-', dir=destination.parent))
    (output / 'parse_cache.jsonl').write_text(''.join(cache), encoding='utf-8')
    for name, rows in (('records', all_rows), ('dialogue_examples', examples), ('story_knowledge', lore), ('voice_manifest', voices)):
        (output / f'{name}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # Publish only after every output succeeds. Interrupted staging directories are inactive.
    output.rename(destination)
    return report
