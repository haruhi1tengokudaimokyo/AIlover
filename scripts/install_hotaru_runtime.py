"""Append verified Hotaru evidence and install her without replacing old user data.

The CMVS extraction/training pipeline supplies normalized source_records.jsonl,
dialogue_examples.jsonl and lines_clean.jsonl. No model or network calls.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def append_rows(path, rows):
    # Preserve every byte of pre-existing records; add only a required separator.
    before = path.read_bytes() if path.exists() else b''
    suffix = (b'\n' if before and not before.endswith(b'\n') else b'')
    suffix += ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
    path.write_bytes(before + suffix)
    if not path.read_bytes().startswith(before):
        raise ValueError('Old evidence prefix was modified')


def build_runtime(source, previous, output):
    """Copy a bundle, append only Hotaru and retain the previous lore unchanged."""
    source, previous, output = map(Path, (source, previous, output))
    if output.exists():
        raise ValueError('Choose a new runtime build directory')
    if (source / 'runtime_source_report.json').is_file():
        source_report = json.loads((source / 'runtime_source_report.json').read_text(encoding='utf-8'))
        if source_report.get('source_ledger_sha256') != sha(ROOT / 'extracted/amatsutsumi/source/aligned_records.jsonl'):
            raise ValueError('Runtime sources are stale: CMVS source ledger changed')
    records = read_rows(source / 'source_records.jsonl')
    examples = read_rows(source / 'dialogue_examples.jsonl')
    legacy = read_rows(source / 'lines_clean.jsonl')
    if not records or not examples or not legacy:
        raise ValueError('Hotaru runtime inputs must not be empty')
    for rows in (records, examples):
        if any(row.get('character') != 'hotaru' or not row.get('id') or not row.get('source_sha256')
               or not row.get('source_file') or not row.get('source_location') for row in rows):
            raise ValueError('Hotaru source identity/provenance is incomplete')
        if len({row['id'] for row in rows}) != len(rows):
            raise ValueError('Duplicate Hotaru source IDs')
    by_id = {row['id']: row for row in records}
    for example in examples:
        original = by_id.get(example['id'])
        if not original or example['text'] != original['text'] or example['source_sha256'] != original['source_sha256']:
            raise ValueError('Style example lost its exact source')
        if example.get('evidence_type') != 'style':
            raise ValueError('Examples must be style evidence, not inferred lore')
    old_hashes = {path.name: sha(path) for path in previous.iterdir() if path.is_file()}
    for name, rows in (('records.jsonl', records), ('dialogue_examples.jsonl', examples)):
        old_rows = read_rows(previous / name)
        if any(row.get('character') == 'hotaru' for row in old_rows):
            raise ValueError('Previous bundle already contains Hotaru; use its original baseline')
        if {row['id'] for row in old_rows} & {row['id'] for row in rows}:
            raise ValueError('Cross-game source ID collision')
    shutil.copytree(previous, output)
    append_rows(output / 'records.jsonl', records)
    append_rows(output / 'dialogue_examples.jsonl', examples)
    voices = [dict(id=row['id'], voice_id=row['voice_id'], audio_path=row.get('audio_path'),
                   source_file=row['source_file'], source_location=row['source_location'])
              for row in records if row.get('voice_id')]
    append_rows(output / 'voice_manifest.jsonl', voices)
    if sha(output / 'story_knowledge.jsonl') != old_hashes['story_knowledge.jsonl']:
        raise ValueError('Previous reviewed lore changed')
    if any(sha(previous / name) != digest for name, digest in old_hashes.items()):
        raise ValueError('Previous runtime input was changed')
    report = dict(slug='hotaru', previous=str(previous.resolve()), output=str(output.resolve()),
                  records=len(records), dialogue_examples=len(examples), legacy_style_lines=len(legacy),
                  voice_records=len(voices), inferred_lore_added=0, previous_file_sha256=old_hashes,
                  old_evidence_prefix_bytes_preserved=True,
                  counts=dict(Counter(row.get('character') for row in read_rows(output / 'dialogue_examples.jsonl'))))
    (output / 'hotaru_install.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def snapshot_rows(connection):
    snapshots = {}
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        escaped = '"' + table.replace('"', '""') + '"'
        snapshots[table] = list(connection.execute('SELECT * FROM ' + escaped + ' ORDER BY rowid'))
    return snapshots


def install_database():
    sys.path.insert(0, str(ROOT / 'backend'))
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.contrib.auth.models import User
    from web.models.character import Character
    from web.models.friend import Friend
    db = Path(settings.DATABASES['default']['NAME']).resolve()
    if db != (ROOT / 'backend/db.sqlite3').resolve():
        raise ValueError('Installer only writes the explicitly targeted development database')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = ROOT / 'backend/backups' / ('before-hotaru-' + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(db) as before:
        with sqlite3.connect(backup / 'db.sqlite3') as target:
            before.backup(target)
        old_rows = snapshot_rows(before)
    call_command('seed_amatsutsumi')
    character = Character.objects.get(slug='hotaru', author__user=User.objects.order_by('id').first())
    friend, created = Friend.objects.get_or_create(me=character.author, character=character)
    with sqlite3.connect(db) as after:
        current = snapshot_rows(after)
    for table, rows in old_rows.items():
        if any(row not in current[table] for row in rows):
            raise ValueError('An existing database row was changed: ' + table)
        if table not in ('web_character', 'web_friend') and current[table] != rows:
            raise ValueError('Unexpected database write: ' + table)
    return dict(database=str(db), backup=str(backup / 'db.sqlite3'),
                old_rows_unchanged=True, character_id=character.pk, friend_id=friend.pk,
                friend_created=created, old_row_counts={name: len(rows) for name, rows in old_rows.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'extracted/characters/hotaru')
    parser.add_argument('--previous', type=Path, default=ROOT / 'backend/story_data')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    report = build_runtime(args.source, args.previous, args.output)
    if args.install:
        # Only the known application data directories are writable install targets.
        active = ROOT / 'backend/story_data'
        if args.previous.resolve() != active.resolve():
            raise ValueError('--install requires the active baseline backend/story_data')
        if not args.output.resolve().is_relative_to(ROOT / 'extracted/story_builds'):
            raise ValueError('Runtime builds must stay inside extracted/story_builds')
        legacy_destination = ROOT / 'backend/web/documents/character_lines/hotaru.jsonl'
        if legacy_destination.exists():
            raise ValueError('Refusing to overwrite an already installed legacy style corpus')
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = ROOT / 'backend' / ('story_data-backup-before-hotaru-' + stamp)
        staging = ROOT / 'backend' / ('.story-hotaru-partial-' + stamp)
        legacy_staging = legacy_destination.with_name('hotaru.jsonl.partial-' + stamp)
        if backup.exists() or staging.exists() or legacy_staging.exists():
            raise ValueError('Runtime backup already exists')
        # Finish all large file copies before changing the live directory or DB.
        shutil.copytree(args.output, staging)
        for path in args.output.iterdir():
            if path.is_file() and sha(path) != sha(staging / path.name):
                raise ValueError('Staged runtime copy differs')
        shutil.copyfile(args.source / 'lines_clean.jsonl', legacy_staging)
        if sha(legacy_staging) != sha(args.source / 'lines_clean.jsonl'):
            raise ValueError('Staged legacy style corpus differs')
        report['database_install'] = install_database()
        # Validate both resolved targets before moving this owned runtime directory.
        if active.resolve().parent != (ROOT / 'backend').resolve() or backup.resolve().parent != (ROOT / 'backend').resolve():
            raise ValueError('Unsafe runtime move')
        active.rename(backup)
        try:
            staging.rename(active)
        except OSError:
            backup.rename(active)
            raise
        legacy_staging.rename(legacy_destination)
        report['runtime_backup'] = str(backup)
        report['legacy_sha256'] = sha(legacy_destination)
        (ROOT / 'docs/evaluation/hotaru-install.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
