#!/usr/bin/env python3
"""
Anthropic usage and cost report fetcher.

Queries the Anthropic Admin API for token usage and spend over a date range,
broken down by model and day. Answers the questions:
  - What did this session/period cost?
  - Which models and operations drove the most spend?
  - Where were input vs output tokens concentrated?

Requirements:
  pip install requests python-dateutil

Authentication:
  Requires an Admin API key (sk-ant-admin-*), not a standard API key.
  Create one at: https://console.anthropic.com -> Settings -> Admin Keys

Usage:
  export ANTHROPIC_ADMIN_KEY=sk-ant-admin-...

  # Last 7 days (default)
  python usage_report.py

  # Specific date range
  python usage_report.py --start 2026-03-20 --end 2026-03-27

  # Daily breakdown
  python usage_report.py --bucket 1d

  # Hourly breakdown for a shorter window
  python usage_report.py --start 2026-03-26 --end 2026-03-27 --bucket 1h

  # JSON output (pipe to jq, etc.)
  python usage_report.py --json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://api.anthropic.com"
API_VERSION = "2023-06-01"

# Approximate pricing for Claude models (USD per million tokens).
# Update these if Anthropic adjusts pricing.
# Source: https://www.anthropic.com/pricing
MODEL_PRICING = {
    "claude-opus-4-6":    {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":  {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5":   {"input":  0.80,  "output":  4.00},
    # Cached input reads are 10% of standard input price
    "cache_read_multiplier": 0.10,
}


def get_admin_key() -> str:
    key = os.environ.get("ANTHROPIC_ADMIN_KEY", "")
    if not key:
        print(
            "Error: ANTHROPIC_ADMIN_KEY environment variable not set.\n"
            "Create an Admin key at https://console.anthropic.com -> Settings -> Admin Keys",
            file=sys.stderr,
        )
        sys.exit(1)
    if not key.startswith("sk-ant-admin"):
        print(
            "Warning: key does not look like an Admin key (expected sk-ant-admin-...).\n"
            "Standard API keys cannot access usage endpoints.",
            file=sys.stderr,
        )
    return key


def fetch_paginated(endpoint: str, key: str, params: dict) -> list[dict]:
    """Fetch all pages from a paginated Admin API endpoint."""
    headers = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
    }
    results = []
    page_token = None

    while True:
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(f"{API_BASE}{endpoint}", headers=headers, params=params)

        if resp.status_code == 401:
            print("Error: Unauthorized. Check that your key is a valid Admin key.", file=sys.stderr)
            sys.exit(1)
        if resp.status_code == 403:
            print("Error: Forbidden. Admin keys require organization admin role.", file=sys.stderr)
            sys.exit(1)
        if not resp.ok:
            print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)

        data = resp.json()
        results.extend(data.get("data", []))

        if not data.get("has_more"):
            break
        page_token = data.get("next_page")

    return results


def fetch_usage(key: str, starting_at: str, ending_at: str, bucket: str) -> list[dict]:
    return fetch_paginated(
        "/v1/organizations/usage_report/messages",
        key,
        {
            "starting_at": starting_at,
            "ending_at": ending_at,
            "bucket_width": bucket,
            "group_by": "model",
        },
    )


def fetch_costs(key: str, starting_at: str, ending_at: str, bucket: str) -> list[dict]:
    return fetch_paginated(
        "/v1/organizations/cost_report",
        key,
        {
            "starting_at": starting_at,
            "ending_at": ending_at,
            "bucket_width": bucket,
            "group_by": "model",
        },
    )


def estimate_cost(input_tokens: int, output_tokens: int, cache_read_tokens: int, model: str) -> float:
    """
    Estimate cost in USD from token counts when the cost report is unavailable.
    Falls back to a generic Sonnet price if model is unknown.
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
    cache_multiplier = MODEL_PRICING["cache_read_multiplier"]

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    cache_cost = (cache_read_tokens / 1_000_000) * pricing["input"] * cache_multiplier

    return input_cost + output_cost + cache_cost


def summarize(usage_rows: list[dict], cost_rows: list[dict]) -> dict:
    """Aggregate usage and cost data into a summary structure."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "estimated_cost_usd": 0.0,
        "actual_cost_usd": None,
        "by_model": {},
    }

    for row in usage_rows:
        model = row.get("model", "unknown")
        inp = row.get("input_tokens", 0)
        out = row.get("output_tokens", 0)
        cache_read = row.get("cache_read_input_tokens", 0)
        cache_create = row.get("cache_creation", {}).get("ephemeral_1h_input_tokens", 0)

        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["cache_read_tokens"] += cache_read
        totals["cache_creation_tokens"] += cache_create
        totals["estimated_cost_usd"] += estimate_cost(inp, out, cache_read, model)

        m = totals["by_model"].setdefault(model, {
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "estimated_cost_usd": 0.0,
        })
        m["input_tokens"] += inp
        m["output_tokens"] += out
        m["cache_read_tokens"] += cache_read
        m["estimated_cost_usd"] += estimate_cost(inp, out, cache_read, model)

    # Overlay actual costs from the cost report if available
    if cost_rows:
        actual_total = 0.0
        for row in cost_rows:
            # amount is in lowest currency units (cents * 100); divide by 10000 for USD
            amount_str = row.get("amount", "0")
            actual_total += float(amount_str) / 10_000
        totals["actual_cost_usd"] = round(actual_total, 6)

    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)
    return totals


def print_report(summary: dict, start: str, end: str, bucket: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Anthropic Usage Report")
    print(f"  {start}  →  {end}  (bucket: {bucket})")
    print(f"{'='*60}\n")

    total_tokens = summary["input_tokens"] + summary["output_tokens"]
    cost_display = (
        f"${summary['actual_cost_usd']:.4f} (actual)"
        if summary["actual_cost_usd"] is not None
        else f"~${summary['estimated_cost_usd']:.4f} (estimated from token counts)"
    )

    print(f"  Total tokens      : {total_tokens:>12,}")
    print(f"    Input           : {summary['input_tokens']:>12,}")
    print(f"    Output          : {summary['output_tokens']:>12,}")
    print(f"    Cache reads     : {summary['cache_read_tokens']:>12,}")
    print(f"    Cache creation  : {summary['cache_creation_tokens']:>12,}")
    print(f"  Cost              : {cost_display}")

    if summary["by_model"]:
        print(f"\n  By model:")
        for model, stats in sorted(
            summary["by_model"].items(),
            key=lambda x: x[1]["estimated_cost_usd"],
            reverse=True,
        ):
            tok = stats["input_tokens"] + stats["output_tokens"]
            print(
                f"    {model:<30}  {tok:>10,} tokens  "
                f"~${stats['estimated_cost_usd']:.4f}"
            )

    print(f"\n{'='*60}\n")
    print("Notes:")
    print("  - Estimated costs use published per-model pricing.")
    print("  - Actual costs (if shown) come from the Admin cost report API.")
    print("  - Cache reads are billed at 10% of standard input price.")
    print("  - Run with --json to get raw data for further analysis.")
    print()


def main() -> None:
    now = datetime.now(timezone.utc)
    default_end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    default_start = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    parser = argparse.ArgumentParser(description="Anthropic usage and cost report")
    parser.add_argument("--start", default=default_start, help="Start datetime (ISO 8601, default: 7 days ago)")
    parser.add_argument("--end", default=default_end, help="End datetime (ISO 8601, default: now)")
    parser.add_argument("--bucket", default="1d", choices=["1m", "1h", "1d"], help="Time bucket width")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted report")
    args = parser.parse_args()

    # Accept YYYY-MM-DD shorthand
    for attr in ("start", "end"):
        val = getattr(args, attr)
        if len(val) == 10:
            setattr(args, attr, val + "T00:00:00Z")

    key = get_admin_key()

    usage_rows = fetch_usage(key, args.start, args.end, args.bucket)
    cost_rows = fetch_costs(key, args.start, args.end, args.bucket)

    summary = summarize(usage_rows, cost_rows)

    if args.json:
        print(json.dumps({
            "period": {"start": args.start, "end": args.end, "bucket": args.bucket},
            "summary": summary,
            "raw_usage": usage_rows,
            "raw_costs": cost_rows,
        }, indent=2))
    else:
        print_report(summary, args.start, args.end, args.bucket)


if __name__ == "__main__":
    main()
