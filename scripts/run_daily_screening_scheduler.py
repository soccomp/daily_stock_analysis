"""Run the daily autonomous screening scheduler once (LaunchAgent entrypoint).

This is a thin trigger: it decides whether to run today's screening, runs the
existing screening service at most once, and records the scheduling outcome.
It is idempotent, bounded-retry, and fail-soft.

Usage:
  scripts/run_daily_screening_scheduler.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.investment.screening_scheduler import build_scheduler  # noqa: E402

STATE_PATH = ROOT / "data" / "screening" / "scheduler_state.json"


def main() -> int:
    scheduler = build_scheduler(STATE_PATH)
    result = scheduler.tick()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # Exit 0 regardless: the scheduling outcome is recorded, not a process error.
    return 0


if __name__ == "__main__":
    sys.exit(main())
