"""Test-wide database isolation.

`app/db/session.py` builds its engine AT IMPORT TIME from `DATABASE_URL`, and
`app/services/snapshot_client.py` calls `Base.metadata.create_all` at import time
too. The database a test run talks to is therefore decided by whichever `app.*`
module gets imported first - which is decided by the alphabetical order of test
files. `create_all` does not add columns to tables that already exist, so an old
`participation.db` lying in the working tree (2026-08-06 in this repo) silently
supplies a stale schema, and the failure surfaces far away:

    sqlite3.OperationalError: no such column: fatigue_snapshots.vote_event_id

That is a test-order dependency, not a defect in the code under test. Adding one
test file that happens to import `governor_client` (which pulls `snapshot_client`)
was enough to break five API tests that pass on their own. Setting the variable
here fixes the class: conftest is imported before any test module, so every run
starts from one fresh, complete schema regardless of collection order.
"""

import atexit
import os
import shutil
import tempfile

_KATALOG = tempfile.mkdtemp(prefix="pa-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_KATALOG}/tests.db")

# Sprzątanie po przebiegu. Bez tego każde uruchomienie pytest zostawia katalog z bazą,
# a w tym repozytorium testy chodzą po kilkanaście razy dziennie - po tygodniu w /tmp
# leżą setki nieużywanych baz. `ignore_errors`, bo nieudane sprzątanie nie ma prawa
# przesłonić wyniku testów.
atexit.register(lambda: shutil.rmtree(_KATALOG, ignore_errors=True))
