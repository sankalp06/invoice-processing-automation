"""
run_email_scanner.py
─────────────────────
Entry point for the email scanning workflow.

Usage
─────
    python run_email_scanner.py                         # default lookback from .env
    python run_email_scanner.py --lookback-hours 48     # override lookback
    python run_email_scanner.py --dry-run               # list messages only
"""
from __future__ import annotations

import argparse
import sys

# Load .env before any other imports so settings picks up credentials
from dotenv import load_dotenv
load_dotenv(override=True)

from config.settings import settings
from shared.clients.blob_client import AzureBlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient
from shared.clients.graph_client import MSGraphClient
from shared.clients.translator_client import AzureTranslatorClient
from shared.utils.logging import setup_logging
from workflows.email_scanner.services.email_scanner_pipeline import EmailScannerPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan mailbox and validate invoice attachments.")
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=settings.email_lookback_hours,
        help=f"Hours of inbox history to scan (default: {settings.email_lookback_hours}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List emails only — do not process attachments or send notifications.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    import logging
    logger = logging.getLogger(__name__)

    logger.info(
        "Email scanner starting — mailbox=%s  lookback=%dh",
        settings.mailbox,
        args.lookback_hours,
    )

    graph = MSGraphClient()

    if args.dry_run:
        messages = graph.list_messages(lookback_hours=args.lookback_hours)
        logger.info("Dry run — %d message(s) found:", len(messages))
        for m in messages:
            sender = m.get("from", {}).get("emailAddress", {}).get("address", "?")
            print(f"  [{m.get('receivedDateTime','')}] {sender}: {m.get('subject','')}")
        return 0

    pipeline = EmailScannerPipeline(
        graph_client=graph,
        blob_client=AzureBlobStorageClient(),
        doc_intel_client=AzureDocumentIntelligenceClient(),
        translator_client=AzureTranslatorClient(),
    )

    scan = pipeline.run(lookback_hours=args.lookback_hours)

    # ── Print summary ────────────────────────────────────────────────────────
    logger.info("═" * 60)
    logger.info("SCAN SUMMARY")
    logger.info("  Messages scanned       : %d", scan.messages_scanned)
    logger.info("  Messages with attachments: %d", scan.messages_with_attachments)
    logger.info("  Total attachments      : %d", scan.total_attachments)
    logger.info("  Valid invoices stored  : %d", scan.valid_invoices)
    logger.info("  Invalid / rejected     : %d", scan.invalid_invoices)
    logger.info("═" * 60)

    return 0 if scan.invalid_invoices == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
