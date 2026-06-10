#!/usr/bin/env python3
"""Executa job de lembretes de agenda (cron)."""
from __future__ import annotations

import os
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from services.jobs.scheduling_reminders import run_scheduling_reminders


def main() -> int:
    out = run_scheduling_reminders()
    print(out)
    if not out.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
