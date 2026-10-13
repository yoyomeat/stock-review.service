import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app import app
import pytest

@pytest.fixture(scope='session')
def client():
    return TestClient(app)
