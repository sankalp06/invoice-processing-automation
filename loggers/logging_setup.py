"""
loggers/logging_setup.py
─────────────────────────
Centralised logging configuration.  Call setup_logging() once at startup.
"""
from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%SZ"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(numeric)
    root.handlers.clear()
    root.addHandler(handler)

    # Quieten noisy Azure SDK HTTP logs
    if numeric > logging.DEBUG:
        logging.getLogger(
            "azure.core.pipeline.policies.http_logging_policy"
        ).setLevel(logging.WARNING)
