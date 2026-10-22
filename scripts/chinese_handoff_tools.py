"""Offline Chinese handoff verification and explicit local TTS experiment tools."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import wave

BASE = Path(__file__).resolve().parent
KANA = re.compile(r'[\u3040-\u30ff\uff66-\uff9f]')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def contained(root, relative):
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or ':' in relative or '\\' in relative:
        raise ValueError('Unsafe relative path')
    path = (root / Path(*rel.parts)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Path outside package')
    return path


def verify(root):
    for name, info in read_json(root / 'manifest.json')['files'].items():
        path = contained(root, name)
        if path.stat().st_size != info['bytes'] or sha(path) != info['sha256']:
            raise ValueError('File checksum mismatch: ' + name)
    package = read_json(root / 'package.json')
    if package['kind'] == 'text':
        ids, targets = {}, {}
        counts = {}
        for split in ('train', 'validation'):
            rows = read_json(root / f'sft/{split}.json')
            counts[split] = len(rows)
            ids[split], targets[split] = set(), set()
            for row in rows:
                if KANA.search(row['system']) or len(row['conversations']) != 2:
                    raise ValueError('Invalid Chinese system or conversation')
                human, assistant = row['conversations']
                if human['from'] != 'human' or assistant['from'] != 'gpt':
                    raise ValueError('Wrong conversation roles')
                if any(not c['value'].strip() or KANA.search(c['value']) for c in (human, assistant)):
                    raise ValueError('Non-Chinese/empty training text')
                ids[split].add(human['value'] + '\n' + assistant['value'])
                targets[split].add(assistant['value'])
        if not all(counts.values()) or ids['train'] & ids['validation'] or targets['train'] & targets['validation']:
            raise ValueError('Empty split or evaluation leakage')
        return dict(counts, japanese_kana_in_training=0)
    slug = package['slug']
    lines = (root / 'labels/fewshot_10min_ja.list').read_text(encoding='utf-8').splitlines()
    seen, seconds = set(), 0
    for line in lines:
        p, speaker, language, text = line.split('|', 3)
        if speaker != slug or language != 'ja' or not text or p in seen:
            raise ValueError('Incorrect reference-language annotation')
        seen.add(p)
        with wave.open(str(contained(root, p)), 'rb') as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 32000):
                raise ValueError('Incorrect WAV format')
            seconds += w.getnframes() / w.getframerate()
    if not 540 <= seconds <= 600:
        raise ValueError('Few-shot duration outside selected budget')
    return {'optional_ja_adaptation_minutes': round(seconds / 60, 2), 'target_language': 'zh',
            'actual_chinese_speech_training_files': 0, 'audio_labels': len(lines)}


def paths(root):
    lines = []
    for row in (root / 'labels/fewshot_10min_ja.list').read_text(encoding='utf-8').splitlines():
        relative, speaker, language, text = row.split('|', 3)
        path = contained(root, relative)
        if not path.is_file():
            raise ValueError('Missing adaptation file')
        lines.append('|'.join((path.as_posix(), speaker, language, text)))
    (root / 'train_optional_ja.list').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'written': 'train_optional_ja.list', 'not_a_chinese_recording_dataset': True}


def tts_request(root, text, reference=1):
    if not text.strip() or KANA.search(text):
        raise ValueError('Output text must be Chinese without Japanese kana')
    slug = read_json(root / 'package.json')['slug']
    wav = root / 'reference' / f'{slug}_ref_{reference}.wav'
    if not wav.is_file():
        raise ValueError('Reference does not exist')
    return {'text': text, 'text_lang': 'zh', 'ref_audio_path': wav.resolve().as_posix(),
            'prompt_text': wav.with_suffix('.txt').read_text(encoding='utf-8'), 'prompt_lang': 'ja',
            'text_split_method': 'cut5', 'media_type': 'wav', 'streaming_mode': False, 'seed': 20261022}


def synthesize(root, text, url, reference):
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username:
        raise ValueError('This helper only calls an explicitly started localhost GPT-SoVITS server')
    payload = tts_request(root, text, reference)
    request = Request(url.rstrip('/') + '/tts', data=json.dumps(payload, ensure_ascii=False).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=180) as response:
        audio = response.read(64 * 1024 * 1024 + 1)
    if len(audio) > 64 * 1024 * 1024:
        raise ValueError('Unexpected response size')
    with wave.open(io.BytesIO(audio), 'rb') as w:
        if not w.getnframes():
            raise ValueError('Empty generated audio')
    output = root / 'generated'
    output.mkdir(exist_ok=True)
    name = hashlib.sha256(text.encode()).hexdigest()[:16] + f'_ref{reference}.wav'
    (output / name).write_bytes(audio)
    return {'file': 'generated/' + name, 'requested_output_language': 'zh',
            'actually_listened': False, 'requires_chinese_ASR_and_human_review': True}


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def edit_distance(a, b):
    previous = list(range(len(b) + 1))
    for i, c in enumerate(a, 1):
        current = [i]
        for j, d in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (c != d)))
        previous = current
    return previous[-1]


def evaluate(root, transcripts):
    expected = {r['id']: r for r in read_rows(root / 'chinese_eval/utterances.jsonl')}
    raw = read_rows(transcripts)
    rows = {r['id']: r for r in raw}
    if len(raw) != len(rows) or not rows or set(rows) - set(expected):
        raise ValueError('Duplicate, unknown, or empty evaluation IDs')
    errors = total = kana = 0
    for ident, row in rows.items():
        reference, actual = normalized(expected[ident]['text']), normalized(row['asr_text'])
        errors += edit_distance(reference, actual)
        total += len(reference)
        kana += bool(KANA.search(row['asr_text']))
    return {'evaluated_cases': len(rows), 'missing_cases': len(expected) - len(rows),
            'chinese_CER': round(errors / max(total, 1), 4), 'kana_in_ASR_cases': kana,
            'voice_similarity': 'not_measured', 'naturalness': 'requires_human_review',
            'language_proof_depends_on_real_ASR_transcripts': True, 'not_a_model_quality_pass_claim': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('verify');sub.add_parser('paths')
    req = sub.add_parser('request');req.add_argument('--text', required=True);req.add_argument('--reference',type=int,default=1)
    run = sub.add_parser('synthesize');run.add_argument('--text',required=True);run.add_argument('--reference',type=int,default=1)
    run.add_argument('--url',default='http://127.0.0.1:9880')
    ev = sub.add_parser('evaluate');ev.add_argument('--transcripts',type=Path,required=True)
    args = parser.parse_args()
    kind = read_json(BASE / 'package.json')['kind']
    if args.command == 'verify':result=verify(BASE)
    elif kind != 'voice':parser.error('Voice experiment command requires a voice package')
    elif args.command == 'paths':result=paths(BASE)
    elif args.command == 'request':result=tts_request(BASE,args.text,args.reference)
    elif args.command == 'synthesize':result=synthesize(BASE,args.text,args.url,args.reference)
    else:result=evaluate(BASE,args.transcripts)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
