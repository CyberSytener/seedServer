#!/usr/bin/env python3
"""
compare_model_tiers.py
======================
Generates the SAME saga prompt using two different model tiers ("cheap" vs
"powerful") and compares the results side-by-side.

Usage:
    python scripts/compare_model_tiers.py [--base-url http://localhost:8000]

The script will:
 1. Seed the gallery (so sub_saga references exist).
 2. Send the same prompt to POST /v1/sagas/architect/draft twice — once with
    model_tier="cheap", once with model_tier="powerful".
 3. Print a comparison table of: model used, validation errors, safety
    verdict, step count, and dry-run outcome.

Requires: httpx (pip install httpx)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


PROMPT = (
    "Build a saga that scans the job market, scores all results, "
    "then sends a notification to the user with the top 5 matches."
)

TIERS = ["cheap", "powerful"]


async def seed_gallery(client: httpx.AsyncClient, base: str) -> None:
    r = await client.post(f"{base}/v1/sagas/blueprints/gallery/seed", timeout=30)
    r.raise_for_status()
    print(f"Gallery seeded: {r.json()}")


async def draft(client: httpx.AsyncClient, base: str, tier: str) -> Dict[str, Any]:
    body = {"prompt": PROMPT, "model_tier": tier, "owner_id": f"compare-{tier}"}
    r = await client.post(
        f"{base}/v1/sagas/architect/draft",
        json=body,
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _fmt_list(items: list) -> str:
    if not items:
        return "(none)"
    return "\n        ".join(f"- {i}" for i in items)


def print_comparison(results: Dict[str, Dict[str, Any]]) -> None:
    sep = "=" * 72
    print(f"\n{sep}")
    print("  MODEL-TIER COMPARISON")
    print(sep)

    for tier, data in results.items():
        model_info = data.get("model") or {}
        safety = data.get("safety") or {}
        dry = data.get("dry_run") or {}
        bp = data.get("blueprint") or {}
        steps = bp.get("steps") or []
        errors = data.get("validation_errors") or []

        print(f"\n--- Tier: {tier.upper()} ---")
        print(f"  Model:              {model_info.get('model_label', '?')} ({model_info.get('model_name', '?')})")
        print(f"  Credit cost:        {model_info.get('credit_cost', '?')}")
        print(f"  Blueprint name:     {bp.get('name', '?')}")
        print(f"  Step count:         {len(steps)}")
        print(f"  Blocks used:        {', '.join(s.get('block') or s.get('block_type', '?') for s in steps)}")
        print(f"  OK:                 {data.get('ok')}")
        print(f"  Status:             {data.get('status', '?')}")
        print(f"  Validation errors:  {_fmt_list(errors)}")
        print(f"  Safety passed:      {safety.get('passed', '?')}")
        print(f"  Safety warnings:    {_fmt_list(safety.get('warnings', []))}")
        print(f"  Dry-run status:     {dry.get('status', 'N/A')}")
        print(f"  Dry-run jobs:       {dry.get('job_count', 'N/A')}")
        print(f"  Dry-run scored:     {dry.get('scored_count', 'N/A')}")
        if data.get("ai_summary"):
            print(f"  AI summary:         {data['ai_summary'][:120]}...")

    # Quick verdict
    print(f"\n{sep}")
    print("  VERDICT")
    print(sep)

    tier_ok = {t: d.get("ok", False) for t, d in results.items()}
    tier_errors = {t: len(d.get("validation_errors") or []) for t, d in results.items()}

    for t in TIERS:
        status_emoji = "PASS" if tier_ok.get(t) else "FAIL"
        err_count = tier_errors.get(t, 0)
        print(f"  {t.upper():12s}  {status_emoji}   validation_errors={err_count}")

    if all(tier_ok.values()):
        print("\n  Both tiers produced valid, safe, sandbox-tested blueprints.")
    elif tier_ok.get("powerful") and not tier_ok.get("cheap"):
        print("\n  The powerful model succeeded where the cheap model failed.")
        print("  Consider upgrading the model tier for complex prompts.")
    elif tier_ok.get("cheap") and not tier_ok.get("powerful"):
        print("\n  Surprisingly, the cheap model succeeded while the powerful model failed.")
        print("  This may indicate a transient issue — re-run to confirm.")
    else:
        print("\n  Both tiers failed. Review the prompt or block registry.")

    print(sep)


async def main(base_url: str) -> None:
    async with httpx.AsyncClient() as client:
        # Step 0: seed gallery so sub_saga references resolve
        print("Seeding blueprint gallery...")
        await seed_gallery(client, base_url)

        # Step 1: draft with each tier
        results: Dict[str, Dict[str, Any]] = {}
        for tier in TIERS:
            print(f"\nDrafting with model_tier='{tier}'...")
            try:
                results[tier] = await draft(client, base_url, tier)
            except httpx.HTTPStatusError as exc:
                print(f"  ERROR: {exc.response.status_code} — {exc.response.text[:200]}")
                results[tier] = {"ok": False, "error": str(exc)}
            except Exception as exc:
                print(f"  ERROR: {exc}")
                results[tier] = {"ok": False, "error": str(exc)}

        # Step 2: compare
        print_comparison(results)

        # Dump raw JSON for debugging
        print("\n--- Raw JSON (for debugging) ---")
        for tier, data in results.items():
            print(f"\n[{tier}]")
            print(json.dumps(data, indent=2, default=str)[:2000])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare saga drafts across model tiers")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
