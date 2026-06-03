"""CI smoke check: ensure critical runtime dependencies are installed.

Exit codes:
 - 0: all good
 - 2: missing modules

Usage (CI):
 python scripts/ci_smoke_check.py
"""

import sys

REQUIRED = ["statsd", "asyncpg", "jwt"]
missing = []
for m in REQUIRED:
    try:
        __import__(m)
    except Exception:
        missing.append(m)

if missing:
    print("MISSING PACKAGES:", ", ".join(missing))
    sys.exit(2)

print("All required runtime modules are present: ", ", ".join(REQUIRED))
sys.exit(0)
