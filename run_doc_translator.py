"""
run_doc_translator.py
──────────────────────
Entry point for the bulk document translation workflow.

Usage
─────
    python run_doc_translator.py
    python run_doc_translator.py --source-lang tr
    python run_doc_translator.py --concurrency 10
    python run_doc_translator.py --dry-run
"""
from __future__ import annotations

import argparse
import sys

# Load .env before any other imports so settings picks up credentials
from dotenv import load_dotenv
load_dotenv(override=True)

from config.settings import settings
from shared.clients.blob_client import BlobStorageClient
from shared.clients.doc_intel_client import AzureDocumentIntelligenceClient
from shared.clients.translator_client import AzureTranslatorClient
from shared.utils.logging import setup_logging
from workflows.doc_translator.services.extraction_service import ExtractionService
from workflows.doc_translator.services.pipeline_service import PipelineService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate all documents in the source container.")
    parser.add_argument("--source-lang", metavar="LANG", default=None)
    parser.add_argument("--concurrency", type=int, default=settings.pipeline_concurrency)
    parser.add_argument("--no-skip", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    import logging
    logger = logging.getLogger(__name__)
    logger.info("Doc translator starting — source=%s  target=%s",
                settings.source_container, settings.target_container)

    if args.dry_run:
        blob_client = BlobStorageClient()
        blobs = list(blob_client.list_blobs(settings.source_container))
        logger.info("Dry run — %d blob(s) in '%s':", len(blobs), settings.source_container)
        for b in blobs:
            print(f"  {b}")
        return 0

    pipeline = PipelineService(
        blob_client=BlobStorageClient(),
        doc_intel_client=AzureDocumentIntelligenceClient(),
        translator_client=AzureTranslatorClient(),
        extraction_service=ExtractionService(),
    )
    results = pipeline.run_batch(
        source_lang=args.source_lang,
        concurrency=args.concurrency,
        skip_if_exists=not args.no_skip,
    )

    failed = [r for r in results if not r.success]
    if failed:
        for r in failed:
            logger.error("  ✗ %s — %s", r.blob_name, r.error)
        return 1
    logger.info("All %d blob(s) processed successfully.", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
