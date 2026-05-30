"""
main.py
────────
Entry point for the document translation pipeline.

Usage
─────
    python main.py                        # auto-detect language, default concurrency
    python main.py --source-lang zh       # force Chinese as source language
    python main.py --concurrency 10       # override concurrency
    python main.py --no-skip              # reprocess blobs that already have a translated counterpart
    python main.py --dry-run              # list blobs only, no processing
"""

from __future__ import annotations

import argparse
import sys

from config.settings import settings
from src.clients.blob_client import AzureBlobStorageClient
from src.clients.doc_intel_client import AzureDocumentIntelligenceClient
from src.clients.translator_client import AzureTranslatorClient
from src.services.extraction_service import ExtractionService
from src.services.pipeline_service import PipelineService
from src.utils.logging import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate all documents in the source Azure container to English."
    )
    parser.add_argument(
        "--source-lang",
        metavar="LANG",
        default=None,
        help="BCP-47 source language code (e.g. 'zh', 'tr'). Omit for auto-detect.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=settings.pipeline_concurrency,
        help=f"Number of parallel workers (default: {settings.pipeline_concurrency}).",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Reprocess blobs even if a translated version already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List blobs in the source container without processing them.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args()


def build_pipeline() -> PipelineService:
    """Construct all clients and wire them into the pipeline."""
    blob_client = AzureBlobStorageClient()
    doc_intel_client = AzureDocumentIntelligenceClient()
    translator_client = AzureTranslatorClient()
    extraction_service = ExtractionService()

    return PipelineService(
        blob_client=blob_client,
        doc_intel_client=doc_intel_client,
        translator_client=translator_client,
        extraction_service=extraction_service,
    )


def main() -> int:
    args = parse_args()
    setup_logging(args.log_level)

    import logging
    logger = logging.getLogger(__name__)

    logger.info(
        "Pipeline starting — source=%s  target=%s",
        settings.source_container,
        settings.target_container,
    )

    # ── Dry run ─────────────────────────────────────────────────────────────
    if args.dry_run:
        blob_client = AzureBlobStorageClient()
        blobs = list(blob_client.list_blobs(settings.source_container))
        logger.info("Dry run — %d blob(s) found in '%s':", len(blobs), settings.source_container)
        for b in blobs:
            print(f"  {b}")
        return 0

    # ── Full batch run ───────────────────────────────────────────────────────
    pipeline = build_pipeline()
    results = pipeline.run_batch(
        source_lang=args.source_lang,
        concurrency=args.concurrency,
        skip_if_exists=not args.no_skip,
    )

    # ── Summary ──────────────────────────────────────────────────────────────
    failed = [r for r in results if not r.success]
    if failed:
        logger.error("%d blob(s) failed to process:", len(failed))
        for r in failed:
            logger.error("  ✗ %s — %s", r.blob_name, r.error)
        return 1

    logger.info("All %d blob(s) processed successfully.", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
