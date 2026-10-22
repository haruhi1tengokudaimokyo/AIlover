"""Portable training handoff tools. Standard-library verification; explicit API opt-in."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
import wave

BASE = Path(__file__).resolve().parent
KANA = re.compile(r'[\u3040-\u30ff\uff66-\uff9f]')
HAN = re.compile(r'[\u3400-\u9fff]')
MUTABLE = {'output/sharegpt.json', 'output/dataset_info.json', 'output/build_report.json'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_rows(path, strict=True):
    rows, errors = [], []
    if not Path(path).exists():
        return rows, errors
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if strict:
                raise ValueError(f'Invalid source JSON at line {number}') from None
            errors.append(number)
    return rows, errors


def safe_path(base, relative):
    p = PurePosixPath(relative)
    if not relative or p.is_absolute() or '\\' in relative or ':' in relative or '..' in p.parts:
        raise ValueError('Unsafe package-relative path')
    target = (base / Path(*p.parts)).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ValueError('Path outside package')
    return target


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def translation_error(record, source):
    if not isinstance(record, dict):
        return 'invalid_record'
    if not isinstance(record.get('id'), str):
        return 'invalid_record_id'
    if record.get('mock') or record.get('qc_note') or record.get('qc_reason'):
        return 'mock_or_qc_placeholder'
    if not source or record.get('character') != source['character']:
        return 'unknown_source_or_character'
    if any(record.get(key) != source.get(key) for key in ('id', 'source_file', 'source_sha256')):
        return 'source_identity_mismatch'
    if record.get('text_src') != source['text']:
        return 'source_text_mismatch'
    target = record.get('text_zh')
    if not isinstance(target, str) or not HAN.search(target) or KANA.search(target) or target == source['text']:
        return 'target_not_chinese_translation'
    context = record.get('context_zh')
    if not isinstance(context, list) or any(not isinstance(c, dict) for c in context):
        return 'invalid_context'
    originals = source.get('context', [])
    if [c.get('id') for c in context] != [c['id'] for c in originals]:
        return 'context_ids_mismatch'
    for old, new in zip(originals, context):
        text = new.get('text')
        if new.get('speaker') != old.get('speaker'):
            return 'context_speaker_mismatch'
        if not isinstance(text, str) or not text.strip() or KANA.search(text):
            return 'context_not_translated'
    return None


def registration(filename):
    return {'file_name': filename, 'formatting': 'sharegpt',
            'columns': {'messages': 'conversations', 'system': 'system'},
            'tags': {'role_tag': 'from', 'content_tag': 'value', 'user_tag': 'human', 'assistant_tag': 'gpt'}}


def convert(base, translated=None):
    package = read_json(base / 'package.json')
    rows, _ = read_rows(base / 'source/dialogue_examples.jsonl')
    sources = {row['id']: row for row in rows}
    translated = Path(translated) if translated else base / 'output/translated.jsonl'
    records, broken = read_rows(translated, strict=False)
    accepted, rejected = {}, Counter()
    for record in records:
        ident = record.get('id') if isinstance(record, dict) else None
        source = sources.get(ident) if isinstance(ident, str) else None
        reason = translation_error(record, source)
        if reason:
            rejected[reason] += 1
        else:
            accepted[record['id']] = record  # Last valid revision wins, invalid lines never erase a valid one.
    glossary = read_json(base / 'glossary.json')['speaker_map']
    system = (base / 'system.txt').read_text(encoding='utf-8')
    samples = []
    for source in rows:
        record = accepted.get(source['id'])
        if record is None:
            continue
        context = '\n'.join(f"{glossary.get(c.get('speaker') or '地', c.get('speaker') or '旁白')}：{c['text']}"
                            for c in record['context_zh'])
        samples.append({'system': system, 'conversations': [
            {'from': 'human', 'value': context or f"{package['name']}，陪我聊会儿吧。"},
            {'from': 'gpt', 'value': record['text_zh']}]})
    output = base / 'output'
    output.mkdir(exist_ok=True)
    (output / 'sharegpt.json').write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')
    info = {f"ousama_{package['slug']}_seed": registration('seed_samples.json')}
    if samples:
        info[f"ousama_{package['slug']}_corpus"] = registration('sharegpt.json')
    (output / 'dataset_info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'source_records': len(rows), 'accepted_translations': len(samples),
              'rejected_records': dict(rejected), 'malformed_json_lines': broken,
              'full_translation_complete': bool(rows) and len(samples) == len(rows), 'models_trained': False}
    (output / 'build_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def translate(base, model, limit):
    # No implicit network in verify/convert/paths. Credentials are environment-only and never packaged/logged.
    if not os.getenv('API_KEY') or not model:
        raise ValueError('Set API_KEY and pass --model before explicit translation')
    from openai import OpenAI
    client = OpenAI(api_key=os.environ['API_KEY'], base_url=os.getenv('API_BASE') or 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    rows, _ = read_rows(base / 'source/dialogue_examples.jsonl')
    source = {r['id']: r for r in rows}
    output = base / 'output/translated.jsonl'
    prior, _ = read_rows(output, strict=False)
    done = {r['id'] for r in prior if isinstance(r, dict) and isinstance(r.get('id'), str)
            and not translation_error(r, source.get(r['id']))}
    todo = [r for r in rows if r['id'] not in done]
    if limit is not None:
        todo = todo[:limit]
    glossary = read_json(base / 'glossary.json')['entries']
    failures = 0
    try:
        for row in todo:
            result = None
            for attempt in range(3):
                try:
                    reply = client.chat.completions.create(model=model, temperature=.3, response_format={'type': 'json_object'}, messages=[
                        {'role': 'system', 'content': '把日文目标及前文翻成自然简体中文，保留人物语气，遵循glossary。只返回JSON：{"text":"目标中文","context":[{"id":"保留原ID","text":"中文"}]}。context仅前文，严格保持所有ID及顺序。不要附加解释。'},
                        {'role': 'user', 'content': json.dumps({'glossary': glossary, 'target': {'id': row['id'], 'speaker': row['speaker'], 'text': row['text']}, 'context': row['context']}, ensure_ascii=False)}])
                    data = json.loads(reply.choices[0].message.content)
                    ctx = data.get('context')
                    if not isinstance(ctx, list) or any(not isinstance(c, dict) for c in ctx):
                        raise ValueError('Invalid translated context')
                    if [c.get('id') for c in ctx] != [c['id'] for c in row['context']]:
                        raise ValueError('Wrong translated context IDs')
                    result = {'id': row['id'], 'character': row['character'], 'source_file': row['source_file'],
                              'source_sha256': row['source_sha256'], 'text_src': row['text'], 'text_zh': data.get('text'),
                              'context_zh': [dict(old, text=new.get('text')) for old, new in zip(row['context'], ctx)]}
                    if translation_error(result, row):
                        raise ValueError('Translation failed validation')
                    break
                except Exception as exc:
                    result = None
                    if attempt == 2:
                        print(f"Translation rejected: {row['id']} ({type(exc).__name__})", file=sys.stderr)
                        failures += 1
                    else:
                        time.sleep(2 ** attempt)
            if result is not None:
                # A killed process can leave a partial last line; isolate it before appending the retry.
                if output.exists() and output.stat().st_size:
                    with output.open('rb') as f:
                        f.seek(-1, 2)
                        needs_newline = f.read(1) != b'\n'
                else:
                    needs_newline = False
                with output.open('a', encoding='utf-8') as f:
                    f.write(('\n' if needs_newline else '') + json.dumps(result, ensure_ascii=False) + '\n')
    finally:
        client.close()
    report = convert(base)
    report['failed_requests'] = failures
    return report


def voice_labels(base):
    package = read_json(base / 'package.json')
    records = []
    for line in (base / 'labels' / (package['slug'] + '.list')).read_text(encoding='utf-8').splitlines():
        fields = line.split('|', 3)
        if len(fields) != 4 or fields[1:3] != [package['slug'], 'ja'] or not fields[3].strip():
            raise ValueError('Invalid audio annotation')
        path = safe_path(base, fields[0])
        if path.parent != (base / 'dataset' / package['slug']).resolve():
            raise ValueError('Audio outside character dataset')
        records.append((path, fields))
    if len({p for p, _ in records}) != len(records):
        raise ValueError('Repeated audio labels')
    return records


def rewrite_paths(base, dataset_root=None):
    records = voice_labels(base)
    package = read_json(base / 'package.json')
    root = Path(dataset_root).resolve() if dataset_root else (base / 'dataset').resolve()
    rows = []
    for old, fields in records:
        path = root / package['slug'] / old.name
        if not path.is_file():
            raise ValueError('Dataset file missing at requested destination')
        rows.append('|'.join([path.as_posix(), *fields[1:]]))
    (base / 'train.list').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return {'training_labels': len(rows), 'written': 'train.list'}


def verify(base):
    manifest = read_json(base / 'manifest.json')['files']
    checked = 0
    for relative, entry in manifest.items():
        if relative in MUTABLE:
            continue
        path = safe_path(base, relative)
        if path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise ValueError(f'Checksum mismatch: {relative}')
        checked += 1
    package = read_json(base / 'package.json')
    if package['kind'] == 'voice':
        records = voice_labels(base)
        seconds = 0
        for path, _ in records:
            with wave.open(str(path), 'rb') as w:
                if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 32000):
                    raise ValueError('Incorrect WAV format')
                seconds += w.getnframes() / w.getframerate()
                if not 2 <= w.getnframes() / w.getframerate() <= 15:
                    raise ValueError('Incorrect WAV duration')
        return {'verified_files': checked, 'training_labels': len(records), 'duration_seconds': round(seconds, 3)}
    seeds = read_json(base / 'output/seed_samples.json')
    rows, _ = read_rows(base / 'source/dialogue_examples.jsonl')
    if not rows or len({r['id'] for r in rows}) != len(rows) or len(seeds) != 5:
        raise ValueError('Invalid text package records')
    return {'verified_files': checked, 'japanese_sources': len(rows), 'chinese_adaptation_seeds': len(seeds)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify')
    paths = commands.add_parser('paths')
    paths.add_argument('--dataset-root')
    conversion = commands.add_parser('convert')
    conversion.add_argument('--translated-input')
    translation = commands.add_parser('translate')
    translation.add_argument('--model', required=True)
    translation.add_argument('--limit', type=int)
    args = parser.parse_args()
    package = read_json(BASE / 'package.json')
    if args.command == 'verify':
        report = verify(BASE)
    elif args.command == 'paths' and package['kind'] == 'voice':
        report = rewrite_paths(BASE, args.dataset_root)
    elif args.command == 'convert' and package['kind'] == 'text':
        report = convert(BASE, args.translated_input)
    elif args.command == 'translate' and package['kind'] == 'text':
        if args.limit is not None and args.limit < 1:
            parser.error('--limit must be positive')
        report = translate(BASE, args.model, args.limit)
    else:
        parser.error('Command does not apply to this package type')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
