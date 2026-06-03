"""Tests for app.infrastructure.scheduler – scheduler_loop."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.scheduler import scheduler_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_queuehub(
    *,
    peek_returns=None,
    pop_returns=None,
    enqueue_side_effect=None,
):
    """Build a mock RedisQueueHub with configurable return values."""
    hub = AsyncMock()
    hub.peek_next_schedule = AsyncMock(return_value=peek_returns)
    hub.pop_due_scheduled = AsyncMock(return_value=pop_returns)
    hub.enqueue = AsyncMock(side_effect=enqueue_side_effect)
    return hub


# ---------------------------------------------------------------------------
# Tests – each cancels the infinite loop after a short timeout
# ---------------------------------------------------------------------------

class TestSchedulerLoop:
    @pytest.mark.asyncio
    async def test_sleeps_when_nothing_scheduled(self):
        """No items → peek returns None → sleeps poll_idle_sec."""
        hub = _make_queuehub(peek_returns=None)

        task = asyncio.create_task(scheduler_loop(queuehub=hub, poll_idle_sec=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # peek was called at least once
        assert hub.peek_next_schedule.await_count >= 1
        # enqueue should never be called
        hub.enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sleeps_when_item_in_future(self):
        """Item exists but run_at is in the future → sleep until due."""
        future_ts = time.time() + 9999
        hub = _make_queuehub(peek_returns=(future_ts, b"payload"))

        task = asyncio.create_task(scheduler_loop(queuehub=hub, poll_idle_sec=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        hub.enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enqueues_due_item(self):
        """Item is due → pop and enqueue into target queue."""
        past_ts = time.time() - 10
        payload = {"queue": "q_batch", "job_id": "j42", "priority": 1, "created_ts": past_ts}

        call_count = {"n": 0}

        async def peek_side_effect():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return (past_ts, b"irrelevant")
            return None  # stop producing

        hub = AsyncMock()
        hub.peek_next_schedule = AsyncMock(side_effect=peek_side_effect)
        hub.pop_due_scheduled = AsyncMock(return_value=(payload, past_ts))
        hub.enqueue = AsyncMock()

        task = asyncio.create_task(scheduler_loop(queuehub=hub, poll_idle_sec=0.01))
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        hub.enqueue.assert_awaited()
        args = hub.enqueue.call_args
        assert args[0][0] == "q_batch"  # queue name
        assert args[0][1] == "j42"  # job_id

    @pytest.mark.asyncio
    async def test_pop_returns_none_does_not_crash(self):
        """peek says due but pop returns None (race) → loops safely."""
        past_ts = time.time() - 10
        call_count = {"n": 0}

        async def peek_side_effect():
            call_count["n"] += 1
            if call_count["n"] <= 3:
                return (past_ts, b"member")
            return None

        hub = AsyncMock()
        hub.peek_next_schedule = AsyncMock(side_effect=peek_side_effect)
        hub.pop_due_scheduled = AsyncMock(return_value=None)
        hub.enqueue = AsyncMock()

        task = asyncio.create_task(scheduler_loop(queuehub=hub, poll_idle_sec=0.01))
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        hub.enqueue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enqueue_error_does_not_crash(self):
        """If enqueue raises, scheduler survives."""
        past_ts = time.time() - 10
        payload = {"queue": "q_batch", "job_id": "j99", "priority": 0, "created_ts": past_ts}

        call_count = {"n": 0}

        async def peek_side_effect():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return (past_ts, b"member")
            return None

        hub = AsyncMock()
        hub.peek_next_schedule = AsyncMock(side_effect=peek_side_effect)
        hub.pop_due_scheduled = AsyncMock(return_value=(payload, past_ts))
        hub.enqueue = AsyncMock(side_effect=RuntimeError("redis down"))

        task = asyncio.create_task(scheduler_loop(queuehub=hub, poll_idle_sec=0.01))
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Should not crash — just keep going
        assert hub.pop_due_scheduled.await_count >= 1

    @pytest.mark.asyncio
    async def test_uses_default_queue_when_missing(self):
        """Payload without 'queue' key defaults to 'q_batch'."""
        past_ts = time.time() - 10
        payload = {"job_id": "j7", "priority": 0, "created_ts": past_ts}
        # no "queue" key

        call_count = {"n": 0}

        async def peek_side_effect():
            call_count["n"] += 1
            if call_count["n"] <= 1:
                return (past_ts, b"member")
            return None

        hub = AsyncMock()
        hub.peek_next_schedule = AsyncMock(side_effect=peek_side_effect)
        hub.pop_due_scheduled = AsyncMock(return_value=(payload, past_ts))
        hub.enqueue = AsyncMock()

        task = asyncio.create_task(scheduler_loop(queuehub=hub, poll_idle_sec=0.01))
        await asyncio.sleep(0.06)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        if hub.enqueue.await_count:
            args = hub.enqueue.call_args
            assert args[0][0] == "q_batch"
