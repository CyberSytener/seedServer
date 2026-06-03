from __future__ import annotations

import logging


class PerformanceMonitor:
    def __init__(self, db) -> None:
        self._db = db
        logging.info("PerformanceMonitor stub initialized")

    def record(self, *args, **kwargs) -> None:
        return None
