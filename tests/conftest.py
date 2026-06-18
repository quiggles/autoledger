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
2. Wipe the three data files before and after every test (``_isolated_data``,
   autouse) so no test can see another's records.

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
_TMP_DATA_DIR = tempfile.mkdtemp(prefix="autoledger-tests-")
os.environ["DATA_DIR"] = _TMP_DATA_DIR

# Make the project root importable when pytest is invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402  (must follow the env/sys.path setup above)

from app import app as flask_app  # noqa: E402
from routes import data as data_module  # noqa: E402

# Every file the storage layer can touch — cleared between tests.
_DATA_FILES = (
    data_module.DATA_FILE,
    data_module.VEHICLES_FILE,
    data_module.SETTINGS_FILE,
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
def client():
    """A Flask test client with TESTING enabled (full error propagation)."""
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as test_client:
        yield test_client


@pytest.fixture
def vehicle(client):
    """Create and return one vehicle; most cost/report tests need a vehicle_id."""
    resp = client.post("/api/vehicles", json={"name": "Test Car", "make": "Vauxhall"})
    assert resp.status_code == 201
    return resp.get_json()
