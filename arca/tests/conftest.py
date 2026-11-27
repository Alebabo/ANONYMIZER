from __future__ import annotations

import pytest

from anonymizer.detect import Detector

from arca import vault_db
from arca.anonymize import ArcaAnonymizer
from arca.release import init_visible

SECRET = b"test-secret-0123456789abcdef0123456789"


@pytest.fixture(scope="session")
def detector() -> Detector:
    return Detector()


@pytest.fixture()
def paths(tmp_path):
    vault_path, visible_path = tmp_path / "vault.db", tmp_path / "visible.db"
    init_visible(visible_path)
    return vault_path, visible_path


@pytest.fixture()
def vault(paths):
    conn = vault_db.connect(paths[0])
    vault_db.seed(conn)
    yield conn
    conn.close()


@pytest.fixture()
def arca(vault, detector) -> ArcaAnonymizer:
    return ArcaAnonymizer(vault, SECRET, detector)
