"""
tests/conftest.py
-----------------
Shared pytest fixtures for the AutoLedger suite.

Isolation strategy
------------------
All persistence in AutoLedger goes through flat JSON files whose paths are
derived from the ``DATA_DIR`` environment variable at *import time*
(``routes/data.py``). To keep tests hermetic we therefore:

1. Point ``DATA_DIR`` at a throwaway temp directory **before** the application
   package is imported, so every module-level path constant resolves inside it.
2. Wipe the data files (and auth/secret artefacts) before and after every test
   (``_isolated_data``, autouse) so no test can see another's state.

Authentication
--------------
As of v2.0.0 every ``/api/*`` route is protected by the auth guard. The default
``client`` fixture therefore **onboards an admin and logs in**, so the bulk of
the suite (costs, vehicles, reports, import/export) exercises endpoints exactly
as an authenticated user would. Tests that need an unauthenticated client (the
auth flow itself) use the ``anon_client`` fixture instead.

This gives each test a pristine, empty data store without needing a database
or any mocking of the file layer.
"""

import os
import sys
import tempfile
from pathlib import Path

# ── Redirect storage into an isolated temp dir BEFORE importing the app ────────
# This must run at module import time, before `app` (and therefore
# `routes.data`) is imported below, or the path constants will already have
# been computed against the real /data volume.
#
# IMPORTANT — idempotent across re-imports: test modules do
# `from tests.conftest import ...`, which imports this file a SECOND time under
# the ``tests.conftest`` module name (the first is the rootdir conftest plugin).
# A naive ``mkdtemp()`` would run twice and reset ``DATA_DIR`` to a different
# directory on the second import, so the import-time path constants (data.py)
# and the call-time path resolvers (auth/notify/reminders) would disagree and
# the autouse purge would clean the wrong directory. Guarding on an env var
# makes every import share the one temp directory.
if os.environ.get("AUTOLEDGER_TEST_DATA_DIR"):
    _TMP_DATA_DIR = os.environ["AUTOLEDGER_TEST_DATA_DIR"]
else:
    _TMP_DATA_DIR = tempfile.mkdtemp(prefix="autoledger-tests-")
    os.environ["AUTOLEDGER_TEST_DATA_DIR"] = _TMP_DATA_DIR
os.environ["DATA_DIR"] = _TMP_DATA_DIR

# Never start the background reminder scheduler during tests — it would spin up
# a thread for no benefit. Must be set before `app` is imported (the scheduler
# starts at app import time).
os.environ["AUTOLEDGER_DISABLE_SCHEDULER"] = "1"

# Make the project root importable when pytest is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402  (must follow the env/sys.path setup above)

from app import app as flask_app  # noqa: E402
from routes import data as data_module  # noqa: E402

# Test admin credentials used by the authenticated `client` fixture.
TEST_USERNAME = "tester"
TEST_PASSWORD = "test-password-123"

# Every file the storage layer can touch — cleared between tests. Includes the
# auth credential, the session/secret keys, and the notify/reminders stores so
# each test starts from a genuine first-run state.
_DATA_FILES = (
    data_module.DATA_FILE,
    data_module.VEHICLES_FILE,
    data_module.SETTINGS_FILE,
    os.path.join(_TMP_DATA_DIR, "auth.json"),
    os.path.join(_TMP_DATA_DIR, "session.key"),
    os.path.join(_TMP_DATA_DIR, "secret.key"),
    os.path.join(_TMP_DATA_DIR, "notify.json"),
    os.path.join(_TMP_DATA_DIR, "reminders.json"),
)


def _purge() -> None:
    """Delete all data files so the next test starts from empty defaults."""
    for path in _DATA_FILES:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


@pytest.fixture(autouse=True)
def _isolated_data():
    """Guarantee a clean data store before and after each test."""
    _purge()
    yield
    _purge()


@pytest.fixture
def anon_client():
    """An unauthenticated Flask test client (for onboarding/login tests)."""
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


@pytest.fixture
def client(anon_client):
    """
    An **authenticated** test client: onboards a test admin and establishes a
    session, so protected /api/* routes are reachable. The session cookie set by
    onboarding persists across this client's subsequent requests.
    """
    resp = anon_client.post(
        "/api/auth/onboard",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return anon_client


@pytest.fixture
def vehicle(client):
    """Create and return one vehicle; most cost/report tests need a vehicle_id."""
    resp = client.post("/api/vehicles", json={"name": "Test Car", "make": "Vauxhall"})
    assert resp.status_code == 201
    return resp.get_json()
