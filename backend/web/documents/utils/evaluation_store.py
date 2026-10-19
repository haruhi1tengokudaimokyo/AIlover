"""Route evaluation ORM calls to a separate disposable SQLite database.

No fixture transaction, user, message or memory is written to the application DB.
Context-local routing leaves unrelated threads untouched.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import tempfile
import uuid
from django.conf import settings
from django.db import connections, router
from django.core.management import call_command

_database = ContextVar('evaluation_database', default=None)


class EvaluationRouter:
    def db_for_read(self, model, **hints):
        return _database.get()

    def db_for_write(self, model, **hints):
        return _database.get()

    def allow_relation(self, left, right, **hints):
        alias = _database.get()
        if alias:
            return left._state.db == right._state.db == alias
        return None


@contextmanager
def isolated_store():
    root = Path(settings.DATA_DIR) / 'evaluations'
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isolated-', dir=root) as directory:
        alias = 'evaluation_' + uuid.uuid4().hex
        config = dict(connections['default'].settings_dict)
        config.update(NAME=str(Path(directory) / 'evaluation.sqlite3'), ATOMIC_REQUESTS=False,
                      CONN_MAX_AGE=0, TEST={'NAME': None, 'MIRROR': None})
        connections.databases[alias] = config
        evaluator_router = EvaluationRouter()
        router.routers.insert(0, evaluator_router)
        token = _database.set(alias)
        try:
            call_command('migrate', database=alias, interactive=False, verbosity=0)
            yield alias
        finally:
            _database.reset(token)
            router.routers.remove(evaluator_router)
            if alias in connections:
                connections[alias].close()
                del connections[alias]
            connections.databases.pop(alias, None)
