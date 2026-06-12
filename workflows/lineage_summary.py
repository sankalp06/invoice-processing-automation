"""
workflows/lineage_summary.py
─────────────────────────────
Provides:
  - get_lineage_summary_response()   → aggregate metrics (existing)
  - get_attachment_lineage_response() → per-attachment rows with downloadable links (new)

Both are consumed by REST endpoints in function_app.py.
"""
from __future__ import annotations

import logging

from loggers.log_db import get_lineage_summary, get_attachment_lineage

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


def get_attachment_lineage_response(
    period: str = "today",
) -> dict:
    """
    Return per-attachment lineage rows with downloadable SAS file links.

    Parameters
    ----------
    period : One of today / yesterday / last_7_days / last_30_days / overall

    Response shape
    --------------
    {
        "period": "today",
        "total": 12,
        "attachments": [
            {
                "run_id": "...",
                "workflow_name": "DocTranslator",
                "step_name": "extraction_completed",
                "status": "Completed",
                "filename": "invoice_tr.pdf",
                "original_file_link": "https://...?sas...",   // downloadable
                "translated_file_link": "https://...?sas...", // downloadable
                "extracted_json_link": "https://...?sas...",  // downloadable
                "logged_at": "2025-05-30T12:34:56"
            },
            ...
        ]
    }
    """
    period = period.lower().strip()
    if period not in VALID_PERIODS:
        raise ValueError(
            f"Invalid period '{period}'. Valid options: {sorted(VALID_PERIODS)}"
        )

    logger.info("Fetching attachment lineage for period=%s", period)
    rows = get_attachment_lineage(period)

    return {
        "period":      period,
        "total":       len(rows),
        "attachments": rows,
    }
