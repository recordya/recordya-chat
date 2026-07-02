import pytest

from src.db import app_database
from src.db.models import Base


class _RecordingConnection:
    def __init__(self) -> None:
        self.synced_callables: list = []

    async def run_sync(self, fn):  # noqa: ANN001
        self.synced_callables.append(fn)


class _FakeBegin:
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _RecordingConnection:
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.connection = _RecordingConnection()

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection)


@pytest.mark.asyncio
async def test_init_db_creates_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_engine = _FakeEngine()
    monkeypatch.setattr(app_database, "engine", fake_engine)

    await app_database.init_db()

    assert fake_engine.connection.synced_callables == [Base.metadata.create_all]