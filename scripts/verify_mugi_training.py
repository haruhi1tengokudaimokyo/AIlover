"""Verify local Mugi artifacts and refresh verification.json without any API calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import wave

from mugi_filter import mugi_training_usable

ROOT = Path(__file__).resolve().parents[1]
MUGI_DATA = ROOT / 'finetune_data/mugi'


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-previous', action='store_true', help='跳过旧两位文件哈希核对，仍检查麦的全部产物')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('legacy_tts', ROOT / 'finetune_data/tts/build_dataset.py')
    tts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tts)
    original_dir = ROOT / 'extracted/characters/mugi'
    clean_path = original_dir / 'lines_clean.jsonl'
    clean = read_jsonl(clean_path)
    original = {row['id']: row for row in read_jsonl(original_dir / 'source_records.jsonl')}
    sources = read_jsonl(MUGI_DATA / 'llm/source/dialogue_examples.jsonl')
    assert clean and len(clean) == len(sources)
    assert {row['source_id'] for row in clean} == {row['id'] for row in sources}
    assert all(mugi_training_usable(original[row['source_id']]) for row in clean)
    expected = {Path(row['voice']).stem for row in clean}
    dataset = MUGI_DATA / 'tts/dataset/mugi'
    assert {p.stem for p in dataset.glob('*.wav')} == expected, 'Obsolete/missing Mugi WAVs'
    labels = (MUGI_DATA / 'tts/mugi.list').read_text(encoding='utf-8').splitlines()
    durations, seen, wrong_format = [], set(), []
    too_quiet, high_peak = 0, 0
    for wav in dataset.glob('*.wav'):
        with wave.open(str(wav), 'rb') as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (32000, 1, 2):
                wrong_format.append(wav.name)
    for line in labels:
        path, character, language, text = line.split('|', 3)
        assert character == 'mugi' and language == 'ja' and text
        assert path.startswith('DATASET_ROOT/mugi/')
        wav = MUGI_DATA / 'tts' / path.replace('DATASET_ROOT/', 'dataset/')
        assert wav.resolve().parent == dataset.resolve()
        assert wav.stem in expected and wav.stem not in seen
        seen.add(wav.stem)
        duration, rms, peak, _ = tts.wav_info(wav)
        assert 2 <= duration <= 15
        durations.append(duration)
        too_quiet += rms < 100
        high_peak += peak >= .98
    references = []
    for number, stem in enumerate(('vo1_0002', 'vo1_0262', 'vo1_0032'), 1):
        wav = MUGI_DATA / 'tts/reference' / f'mugi_ref_{number}.wav'
        assert digest(wav) == digest(dataset / f'{stem}.wav')
        source_text = next(row['text'] for row in clean if Path(row['voice']).stem == stem)
        assert wav.with_suffix('.txt').read_text(encoding='utf-8') == tts.clean_text(source_text)
        duration, rms, peak, _ = tts.wav_info(wav)
        assert 5 <= duration <= 10 and rms >= 800 and peak < .98
        references.append({'file': wav.relative_to(MUGI_DATA).as_posix(), 'source_voice_id': stem,
                           'duration_seconds': duration, 'rms': rms, 'peak_ratio': peak})
    assert digest(ROOT / 'backend/seed_assets/mugi/voice_ref.opus') == digest(ROOT / 'extracted/voice/vo1_0002.opus')
    seed = json.loads((MUGI_DATA / 'llm/output/seed_samples.json').read_text(encoding='utf-8'))
    llm_summary = json.loads((MUGI_DATA / 'llm/build_summary.json').read_text(encoding='utf-8'))
    assert len(seed) == 5 and llm_summary['source_records'] == len(clean)
    prior, changed = [], None
    baseline = original_dir / 'existing_data_before.json'
    if baseline.exists() and not args.skip_previous:
        prior = json.loads(baseline.read_text(encoding='utf-8'))
        changed = [item['path'] for item in prior
                   if not (ROOT / item['path']).is_file() or digest(ROOT / item['path']) != item['sha256']]
    summary = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
               'clean_sha256': digest(clean_path), 'clean_records': len(clean),
               'wave_files': len(expected), 'llm_source_records': len(sources),
               'chinese_adaptation_seed_samples': len(seed), 'training_labels': len(labels),
               'duration_seconds': round(sum(durations), 3), 'duration_hours': round(sum(durations) / 3600, 3),
               'duration_excluded': len(clean) - len(labels), 'wrong_audio_format': wrong_format,
               'rms_below_100': too_quiet, 'peak_at_or_above_0_98': high_peak,
               'duplicate_training_paths': len(labels) - len(seen), 'references': references,
               'prior_hika_ayame_and_training_files_checked': len(prior), 'prior_files_changed': changed,
               'transcription_manually_listened': False, 'models_trained': False, 'external_api_calls': 0}
    (MUGI_DATA / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    assert not wrong_format and not too_quiet and not changed
    return 0


if __name__ == '__main__':
    sys.exit(main())
