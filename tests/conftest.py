import pytest
import spiceypy as sp

from helpers import LSK


@pytest.fixture(autouse=True)
def clean_pool():
    sp.kclear()
    yield
    sp.kclear()


@pytest.fixture
def lsk(tmp_path):
    path = tmp_path / "test.tls"
    path.write_text(LSK)
    return path
