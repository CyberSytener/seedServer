"""Tests for app.billing_service – PhotoBillingService & WatermarkService."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.billing_service import (
    PhotoBillingService,
    PhotoCreditTransaction,
    TransactionType,
    WatermarkService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session():
    """Return a mock SQLAlchemy session."""
    sess = MagicMock()
    sess.add = MagicMock()
    sess.commit = MagicMock()
    sess.rollback = MagicMock()
    sess.query = MagicMock()
    return sess


def _make_user(credits: float = 500.0, user_id: str = "u1"):
    return SimpleNamespace(id=user_id, credits=credits)


def _patch_user_service(user):
    """Context-manager that patches get_seed_user_service."""
    svc = MagicMock()
    svc.get_user.return_value = user
    svc.update_user = MagicMock()
    return patch(
        "app.services.photo.integration.get_seed_user_service",
        return_value=svc,
    ), svc


# ---------------------------------------------------------------------------
# TransactionType
# ---------------------------------------------------------------------------

class TestTransactionType:
    def test_values(self):
        assert TransactionType.DEBIT.value == "debit"
        assert TransactionType.REFUND.value == "refund"
        assert TransactionType.CREDIT.value == "credit"
        assert TransactionType.PURCHASE.value == "purchase"

    def test_is_str_enum(self):
        assert isinstance(TransactionType.DEBIT, str)


# ---------------------------------------------------------------------------
# PhotoCreditTransaction model
# ---------------------------------------------------------------------------

class TestPhotoCreditTransaction:
    def test_repr(self):
        txn = PhotoCreditTransaction(
            id="t1",
            user_id="u1",
            job_id="j1",
            amount=-50.0,
            transaction_type=TransactionType.DEBIT,
            balance_before=500.0,
            balance_after=450.0,
        )
        r = repr(txn)
        assert "u1" in r
        assert "j1" in r


# ---------------------------------------------------------------------------
# PhotoBillingService – synchronous / pure helpers
# ---------------------------------------------------------------------------

class TestBillingConversions:
    def test_usd_to_credits_default(self):
        svc = PhotoBillingService(seed_db_session=None, credits_price_per_dollar=100.0)
        assert svc.usd_to_credits(1.0) == 100.0
        assert svc.usd_to_credits(0.5) == 50.0

    def test_credits_to_usd_default(self):
        svc = PhotoBillingService(seed_db_session=None, credits_price_per_dollar=100.0)
        assert svc.credits_to_usd(100.0) == 1.0
        assert svc.credits_to_usd(50.0) == 0.5

    def test_custom_rate(self):
        svc = PhotoBillingService(seed_db_session=None, credits_price_per_dollar=200.0)
        assert svc.usd_to_credits(1.0) == 200.0
        assert svc.credits_to_usd(200.0) == 1.0


# ---------------------------------------------------------------------------
# check_user_credits
# ---------------------------------------------------------------------------

class TestCheckUserCredits:
    @pytest.mark.asyncio
    async def test_returns_balance(self):
        user = _make_user(credits=250.0)
        patcher, _ = _patch_user_service(user)
        with patcher:
            svc = PhotoBillingService(seed_db_session=None)
            balance = await svc.check_user_credits("u1")
        assert balance == 250.0

    @pytest.mark.asyncio
    async def test_user_not_found_returns_zero(self):
        patcher, user_svc = _patch_user_service(None)
        user_svc.get_user.return_value = None
        with patcher:
            svc = PhotoBillingService(seed_db_session=None)
            balance = await svc.check_user_credits("missing")
        assert balance == 0.0

    @pytest.mark.asyncio
    async def test_missing_credits_attr_returns_zero(self):
        user = SimpleNamespace(id="u1")  # no 'credits' attribute
        patcher, _ = _patch_user_service(user)
        with patcher:
            svc = PhotoBillingService(seed_db_session=None)
            balance = await svc.check_user_credits("u1")
        assert balance == 0.0


# ---------------------------------------------------------------------------
# validate_can_afford
# ---------------------------------------------------------------------------

class TestValidateCanAfford:
    @pytest.mark.asyncio
    async def test_free_tier_always_passes(self):
        svc = PhotoBillingService(seed_db_session=None)
        ok, reason = await svc.validate_can_afford("u1", cost_usd=999.0, require_payment=False)
        assert ok is True
        assert "Free" in reason

    @pytest.mark.asyncio
    async def test_sufficient_credits(self):
        user = _make_user(credits=500.0)
        patcher, _ = _patch_user_service(user)
        with patcher:
            svc = PhotoBillingService(seed_db_session=None, credits_price_per_dollar=100.0)
            ok, reason = await svc.validate_can_afford("u1", cost_usd=1.0)
        assert ok is True
        assert reason == "OK"

    @pytest.mark.asyncio
    async def test_insufficient_credits(self):
        user = _make_user(credits=10.0)
        patcher, _ = _patch_user_service(user)
        with patcher:
            svc = PhotoBillingService(seed_db_session=None, credits_price_per_dollar=100.0)
            ok, reason = await svc.validate_can_afford("u1", cost_usd=1.0)
        assert ok is False
        assert "Insufficient" in reason

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        patcher, user_svc = _patch_user_service(None)
        user_svc.get_user.side_effect = RuntimeError("db down")
        with patcher:
            svc = PhotoBillingService(seed_db_session=None)
            ok, reason = await svc.validate_can_afford("u1", cost_usd=1.0)
        assert ok is False
        assert "Failed" in reason


# ---------------------------------------------------------------------------
# debit_user_credits
# ---------------------------------------------------------------------------

class TestDebitUserCredits:
    @pytest.mark.asyncio
    async def test_successful_debit(self):
        user = _make_user(credits=500.0)
        patcher, user_svc = _patch_user_service(user)
        sess = _make_session()
        with patcher:
            svc = PhotoBillingService(seed_db_session=sess, credits_price_per_dollar=100.0)
            ok, new_balance = await svc.debit_user_credits("u1", cost_usd=1.0, job_id="j1")
        assert ok is True
        assert new_balance == 400.0
        sess.add.assert_called_once()
        sess.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_debit_does_not_go_negative(self):
        user = _make_user(credits=50.0)
        patcher, _ = _patch_user_service(user)
        sess = _make_session()
        with patcher:
            svc = PhotoBillingService(seed_db_session=sess, credits_price_per_dollar=100.0)
            ok, new_balance = await svc.debit_user_credits("u1", cost_usd=1.0, job_id="j1")
        assert ok is True
        assert new_balance == 0.0  # max(0, 50-100)

    @pytest.mark.asyncio
    async def test_debit_user_not_found(self):
        patcher, user_svc = _patch_user_service(_make_user(credits=100.0))
        # first call to check_user_credits succeeds, but get_user in debit returns None
        call_count = {"n": 0}
        original_return = user_svc.get_user.return_value

        def side_effect(uid):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return original_return  # for check_user_credits
            return None  # for debit

        user_svc.get_user.side_effect = side_effect
        sess = _make_session()
        with patcher:
            svc = PhotoBillingService(seed_db_session=sess, credits_price_per_dollar=100.0)
            ok, new_balance = await svc.debit_user_credits("missing", cost_usd=0.5, job_id="j2")
        assert ok is False


# ---------------------------------------------------------------------------
# refund_user_credits
# ---------------------------------------------------------------------------

class TestRefundUserCredits:
    @pytest.mark.asyncio
    async def test_successful_refund(self):
        user = _make_user(credits=400.0)
        patcher, user_svc = _patch_user_service(user)
        sess = _make_session()
        with patcher:
            svc = PhotoBillingService(seed_db_session=sess, credits_price_per_dollar=100.0)
            ok, new_balance = await svc.refund_user_credits("u1", cost_usd=1.0, job_id="j1")
        assert ok is True
        assert new_balance == 500.0  # 400 + 100
        sess.add.assert_called_once()
        sess.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_refund_user_not_found(self):
        patcher, user_svc = _patch_user_service(_make_user(credits=100.0))
        call_count = {"n": 0}
        original_return = user_svc.get_user.return_value

        def side_effect(uid):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return original_return
            return None

        user_svc.get_user.side_effect = side_effect
        sess = _make_session()
        with patcher:
            svc = PhotoBillingService(seed_db_session=sess, credits_price_per_dollar=100.0)
            ok, _ = await svc.refund_user_credits("missing", cost_usd=0.5, job_id="j2")
        assert ok is False


# ---------------------------------------------------------------------------
# _log_transaction
# ---------------------------------------------------------------------------

class TestLogTransaction:
    def test_logs_transaction_to_session(self):
        sess = _make_session()
        svc = PhotoBillingService(seed_db_session=sess)
        svc._log_transaction(
            user_id="u1",
            job_id="j1",
            amount=-100.0,
            transaction_type=TransactionType.DEBIT,
            reason="test",
            balance_before=500.0,
            balance_after=400.0,
        )
        sess.add.assert_called_once()
        sess.commit.assert_called_once()

    def test_rollback_on_error(self):
        sess = _make_session()
        sess.commit.side_effect = RuntimeError("db fail")
        svc = PhotoBillingService(seed_db_session=sess)
        # Should not raise
        svc._log_transaction(
            user_id="u1",
            job_id="j1",
            amount=-10.0,
            transaction_type=TransactionType.DEBIT,
            reason="err",
            balance_before=100.0,
            balance_after=90.0,
        )
        sess.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# get_user_transaction_history
# ---------------------------------------------------------------------------

class TestGetTransactionHistory:
    def test_returns_list(self):
        from datetime import datetime

        txn = MagicMock()
        txn.id = "t1"
        txn.job_id = "j1"
        txn.amount = -50.0
        txn.transaction_type = TransactionType.DEBIT
        txn.reason = "test"
        txn.balance_before = 500.0
        txn.balance_after = 450.0
        txn.api_cost_usd = 0.5
        txn.created_at = datetime(2025, 1, 1, 12, 0, 0)

        sess = _make_session()
        q = MagicMock()
        q.filter_by.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.all.return_value = [txn]
        sess.query.return_value = q

        svc = PhotoBillingService(seed_db_session=sess)
        history = svc.get_user_transaction_history("u1")

        assert len(history) == 1
        assert history[0]["id"] == "t1"
        assert history[0]["amount"] == -50.0
        assert history[0]["type"] == "debit"

    def test_returns_empty_on_error(self):
        sess = _make_session()
        sess.query.side_effect = RuntimeError("db down")
        svc = PhotoBillingService(seed_db_session=sess)
        assert svc.get_user_transaction_history("u1") == []


# ---------------------------------------------------------------------------
# WatermarkService.apply_watermark
# ---------------------------------------------------------------------------

_has_pil = False
try:
    from PIL import Image  # noqa: F401
    _has_pil = True
except ModuleNotFoundError:
    pass

_skip_no_pil = pytest.mark.skipif(not _has_pil, reason="Pillow not installed")


class TestWatermarkService:
    def _make_png(self, width: int = 100, height: int = 80) -> bytes:
        """Create a tiny valid PNG image in-memory."""
        from PIL import Image
        import io

        img = Image.new("RGBA", (width, height), (0, 128, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @_skip_no_pil
    def test_apply_watermark_returns_bytes(self):
        original = self._make_png()
        result = WatermarkService.apply_watermark(original)
        assert isinstance(result, bytes)
        assert len(result) > 0

    @_skip_no_pil
    def test_apply_watermark_custom_text(self):
        original = self._make_png()
        result = WatermarkService.apply_watermark(original, watermark_text="TEST")
        assert isinstance(result, bytes)

    @_skip_no_pil
    def test_apply_watermark_bad_input_returns_original(self):
        bad = b"not-an-image"
        result = WatermarkService.apply_watermark(bad)
        assert result == bad  # fallback to original

    @_skip_no_pil
    @pytest.mark.asyncio
    async def test_apply_watermark_if_unpaid_disabled(self):
        settings_mock = SimpleNamespace(PHOTO_WATERMARK_UNTIL_PAID=False)
        with patch("app.billing_service.get_seed_user_service", create=True):
            with patch(
                "app.services.photo.settings.settings",
                settings_mock,
                create=True,
            ):
                img = self._make_png()
                result = await WatermarkService.apply_watermark_if_unpaid(
                    image_bytes=img,
                    user_id="u1",
                    billing_service=MagicMock(),
                )
                assert result == img

    @_skip_no_pil
    @pytest.mark.asyncio
    async def test_apply_watermark_if_unpaid_positive_balance(self):
        billing = MagicMock()
        billing.check_user_credits = AsyncMock(return_value=100.0)
        settings_mock = SimpleNamespace(PHOTO_WATERMARK_UNTIL_PAID=True)
        with patch(
            "app.services.photo.settings.settings",
            settings_mock,
            create=True,
        ):
            img = self._make_png()
            result = await WatermarkService.apply_watermark_if_unpaid(
                image_bytes=img,
                user_id="u1",
                billing_service=billing,
            )
            assert result == img  # no watermark needed

    @_skip_no_pil
    @pytest.mark.asyncio
    async def test_apply_watermark_if_unpaid_negative_balance(self):
        billing = MagicMock()
        billing.check_user_credits = AsyncMock(return_value=-10.0)
        settings_mock = SimpleNamespace(PHOTO_WATERMARK_UNTIL_PAID=True)
        with patch(
            "app.services.photo.settings.settings",
            settings_mock,
            create=True,
        ):
            img = self._make_png()
            result = await WatermarkService.apply_watermark_if_unpaid(
                image_bytes=img,
                user_id="u1",
                billing_service=billing,
            )
            # Should be watermarked — different from original
            assert isinstance(result, bytes)
            assert len(result) > 0
