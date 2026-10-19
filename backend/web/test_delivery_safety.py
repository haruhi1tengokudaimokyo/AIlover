import importlib.util
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from django.conf import settings
from django.test import SimpleTestCase


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, Path(settings.BASE_DIR).parent / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeliverySafetyTests(SimpleTestCase):
    def test_review_selection_excludes_original_and_private_runtime_data(self):
        module = load_module('review_selector_fixture','scripts/package_review.py')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ('backend/web/documents/character_lines/hika.jsonl','backend/story_data/records.jsonl',
                             'backend/seed_assets/hika/voice_ref.opus','backend/web/source.py','PROJECT_TECHNICAL_HIGHLIGHTS.md',
                             'docs/real.json','docs/synthetic.json','PROJECT_CORPUS_AUDIT.json'):
                path = root / relative; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('{}',encoding='utf-8')
            (root/'docs/real.json').write_text('{"requires_human_review":true,"offline":false}',encoding='utf-8')
            (root/'docs/synthetic.json').write_text('{"requires_human_review":true,"offline":true}',encoding='utf-8')
            (root/'frontend').mkdir()
            with patch.object(module,'ROOT',root):
                selected = {path.relative_to(root).as_posix() for path in module.collect_files()}
            self.assertIn('backend/web/source.py',selected)
            self.assertIn('docs/synthetic.json',selected)
            self.assertNotIn('docs/real.json',selected)
            self.assertNotIn('PROJECT_CORPUS_AUDIT.json',selected)
            self.assertFalse(any('character_lines' in value or 'seed_assets' in value or 'story_data' in value for value in selected))

    def test_desktop_pending_migration_backs_up_before_schema_change(self):
        module = load_module('launcher_fixture','launcher.py')
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory)/'existing.sqlite3'; database.write_bytes(b'synthetic-existing-database')
            fake_connection = Mock(settings_dict={'NAME':str(database)})
            calls = []
            with patch('django.db.connection',fake_connection), patch('django.db.migrations.executor.MigrationExecutor') as executor, patch('django.core.management.call_command',side_effect=lambda name,**kwargs:calls.append(name)):
                executor.return_value.migration_plan.return_value = [('pending',False)]
                module.migrate_safely()
                self.assertEqual(calls,['backup_data','migrate'])
                calls.clear()
                executor.return_value.migration_plan.return_value = []
                module.migrate_safely()
                self.assertEqual(calls,['migrate'])
