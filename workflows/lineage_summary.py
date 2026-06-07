"""
workflows/lineage_summary.py
─────────────────────────────
Provides the get_lineage_summary_response() function consumed by the
lineage_summary REST endpoint in function_app.py.

Thin layer: validates the period parameter, calls log_db, and shapes
the response dict ready for JSON serialisation.
"""
from __future__ import annotations

import logging

from loggers.log_db import get_lineage_summary

logger = logging.getLogger(__name__)

VALID_PERIODS = {"today", "yesterday", "last_7_days", "last_30_days", "overall"}


def get_lineage_summary_response(
    period: str = "today",
    country_code: str | None = None,
    source_lang: str | None = None,
) -> dict:
    """
    Return the lineage summary dict for the given period.

    Parameters
    ----------
    period       : One of today / yesterday / last_7_days / last_30_days / overall
    country_code : Optional filter (reserved for future use)
    source_lang  : Optional filter (reserved for future use)
    """
    period = period.lower().strip()
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Invalid period '{period}'. Valid options: {sorted(VALID_PERIODS)}"
        )

    logger.info("Fetching lineage summary for period=%s", period)
    summary = get_lineage_summary(period)

    # Attach optional filter metadata so the caller knows what was applied
    summary["filters"] = {
        "country_code": country_code,
        "source_lang":  source_lang,
    }

    return summary
