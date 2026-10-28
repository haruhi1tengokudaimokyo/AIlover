"""Decode the already extracted Hotaru originals; no labels or model calls."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import imageio_ffmpeg
from build_hotaru_training import ROOT, decode_voice
from hotaru_training_common import rows_read, rows_write


def main():
    source = ROOT / 'extracted/amatsutsumi'
    output = ROOT / 'finetune_data/hotaru/preparation-v1'
    inventory = []
    for manifest, archive in [('hotaru_voice_base_extraction.jsonl', 'voice'), ('hotaru_voice_extended_extraction.jsonl', 'voice2')]:
        for row in rows_read(source / 'source' / manifest):
            relative = row['name'].replace('\\', '/')
            path = source / 'voice' / archive / relative
            inventory.append({'voice_id': Path(relative).stem, 'path': path.relative_to(ROOT).as_posix(),
                'sha256': row['sha256'], 'archive_path': '[無碼] 天津罪（アマツツミ）/data/pack/' + archive + '.cpz',
                'archive_entry': relative, 'archive_offset': row['offset']})
    rows_write(output / 'analysis/native_inventory_preflight.jsonl', inventory)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(decode_voice, row, output, ffmpeg) for row in inventory]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results) % 250 == 0:
                print(f'Original Hotaru audio actually decoded/checked: {len(results)}/{len(inventory)}', flush=True)
    rows_write(output / 'analysis/audio_preflight.jsonl', sorted(results, key=lambda row: row['voice_id']))
    print(f'Audio preflight finished: {len(results)}; decode failures={sum(bool(r["decode_error"]) for r in results)}', flush=True)


if __name__ == '__main__':
    main()
