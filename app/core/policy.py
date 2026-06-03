from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


@dataclass(frozen=True)
class Plan:
    id: str
    fast_daily_limit: int
    actions_per_minute_limit: int
    actions_monthly_limit: int
    post_monthly_delay_sec: int
    batch_priority_base: int
    fast_priority_base: int
    max_input_chars: int
    max_output_tokens: int


@dataclass(frozen=True)
class Usage:
    fast_used_today: int
    actions_used_today: int
    actions_used_month: int


@dataclass(frozen=True)
class Policy:
    mode: str
    queue_name: str
    priority: int
    not_before: datetime | None


def estimate_complexity(action: str, input_len: int) -> str:
    if input_len <= 400:
        return "small"
    if input_len <= 3000:
        return "medium"
    return "large"


def decide_policy(
    *,
    plan: Plan,
    usage: Usage,
    action: str,
    input_len: int,
    abuse_score: int,
    system_mode: str,
    rate_delay_sec: int = 0,
) -> Policy:
    abuse_penalty = max(0, min(100, abuse_score))

    # Emergency batch-first
    if system_mode == "emergency":
        return Policy(
            mode="batch",
            queue_name="q_batch",
            priority=plan.batch_priority_base - (abuse_penalty // 2),
            not_before=None,
        )

    # Rate limit -> batch with delay
    if rate_delay_sec > 0:
        nb = datetime.now(timezone.utc) + timedelta(seconds=rate_delay_sec)
        return Policy(
            mode="batch",
            queue_name="q_low",
            priority=plan.batch_priority_base - 80 - abuse_penalty,
            not_before=nb,
        )

    # Monthly limit -> batch with delay
    if plan.actions_monthly_limit > 0 and usage.actions_used_month >= plan.actions_monthly_limit:
        nb = datetime.now(timezone.utc) + timedelta(seconds=plan.post_monthly_delay_sec)
        return Policy(
            mode="batch",
            queue_name="q_low",
            priority=plan.batch_priority_base - 50 - abuse_penalty,
            not_before=nb,
        )

    fast_remaining = plan.fast_daily_limit - usage.fast_used_today
    if plan.fast_daily_limit <= 0:
        fast_remaining = 0
    complexity = estimate_complexity(action, input_len)

    # Fast exhausted -> batch or hybrid
    if fast_remaining <= 0:
        if complexity == "small" and action in ("fix", "translate"):
            return Policy(
                mode="hybrid",
                queue_name="q_batch",
                priority=plan.batch_priority_base - abuse_penalty,
                not_before=None,
            )
        return Policy(
            mode="batch",
            queue_name="q_batch",
            priority=plan.batch_priority_base - abuse_penalty,
            not_before=None,
        )

    # Large tasks: prefer hybrid even if fast available
    if complexity == "large":
        return Policy(
            mode="hybrid",
            queue_name="q_fast",
            priority=plan.fast_priority_base - abuse_penalty,
            not_before=None,
        )

    # Default: fast
    bonus = min(20, max(0, fast_remaining // 2))
    return Policy(
        mode="fast",
        queue_name="q_fast",
        priority=plan.fast_priority_base + bonus - abuse_penalty,
        not_before=None,
    )
