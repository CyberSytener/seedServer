"""Tests for app.infrastructure.db.async_sqlite — AsyncSqliteDB wrapper."""

import asyncio
import pytest

from app.infrastructure.db.sqlite import DB
from app.infrastructure.db.async_sqlite import AsyncSqliteDB


@pytest.fixture()
def async_db(tmp_path):
    path = str(tmp_path / "test.db")
    db = DB(path)
    db.init_schema()
    return AsyncSqliteDB(db)


class TestAsyncSqliteDB:
    @pytest.mark.asyncio
    async def test_execute_and_fetchall(self, async_db: AsyncSqliteDB):
        await async_db.execute(
            "INSERT INTO users(id, email) VALUES (?, ?)",
            ("u1", "a@b.com"),
        )
        rows = await async_db.fetchall(
            "SELECT id, email FROM users WHERE id = ?", ("u1",)
        )
        assert len(rows) == 1
        assert rows[0]["id"] == "u1"
        assert rows[0]["email"] == "a@b.com"

    @pytest.mark.asyncio
    async def test_fetchone_hit(self, async_db: AsyncSqliteDB):
        await async_db.execute(
            "INSERT INTO users(id, email) VALUES (?, ?)",
            ("u2", "b@c.com"),
        )
        row = await async_db.fetchone("SELECT id FROM users WHERE id = ?", ("u2",))
        assert row is not None
        assert row["id"] == "u2"

    @pytest.mark.asyncio
    async def test_fetchone_miss(self, async_db: AsyncSqliteDB):
        row = await async_db.fetchone("SELECT id FROM users WHERE id = ?", ("nonexistent",))
        assert row is None

    @pytest.mark.asyncio
    async def test_transaction_commit(self, async_db: AsyncSqliteDB):
        async with async_db.transaction() as conn:
            conn.execute(
                "INSERT INTO users(id, email) VALUES (?, ?)",
                ("u3", "c@d.com"),
            )
        row = await async_db.fetchone("SELECT id FROM users WHERE id = ?", ("u3",))
        assert row is not None

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, async_db: AsyncSqliteDB):
        with pytest.raises(RuntimeError):
            async with async_db.transaction() as conn:
                conn.execute(
                    "INSERT INTO users(id, email) VALUES (?, ?)",
                    ("u4", "d@e.com"),
                )
                raise RuntimeError("force rollback")
        row = await async_db.fetchone("SELECT id FROM users WHERE id = ?", ("u4",))
        # rollback: user should not exist
        assert row is None

    @pytest.mark.asyncio
    async def test_sync_property(self, async_db: AsyncSqliteDB):
        assert isinstance(async_db.sync, DB)

    @pytest.mark.asyncio
    async def test_close(self, tmp_path):
        path = str(tmp_path / "close_test.db")
        db = DB(path)
        db.init_schema()
        adb = AsyncSqliteDB(db)
        await adb.close()
        # After close, operations should fail
        with pytest.raises(Exception):
            await adb.fetchall("SELECT 1", ())
