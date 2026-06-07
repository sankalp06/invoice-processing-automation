"""
workflows/ocr_pipeline.py
──────────────────────────
PDF OCR + image enhancement pipeline.

Source container  : raw-invoices   (env: SOURCE_CONTAINER)
Target container  : ocr-invoices   (env: TARGET_CONTAINER_OCR)
Failed container  : ocr-failed     (env: FAILED_CONTAINER_OCR)

Changes from the original ocr_add_text_layer.py
────────────────────────────────────────────────
* SAS token → account key via shared BlobStorageClient
* All blob I/O goes through BlobStorageClient; no direct SDK calls
* Lineage steps logged to invoice_process_log via log_db.log_step()
* process_files() signature simplified — reads from config/settings.py;
  callers only need to pass overrides they actually want to change
* Temp-folder management extracted into a context manager
* Each processing path (force_img / normal / fallback) is its own function
  so failure handling is easy to follow and test
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import cv2
import fitz          # PyMuPDF
import numpy as np
import ocrmypdf
from PIL import Image
from pdfminer.high_level import extract_text

from config.settings import settings
from loggers.log_db import Step, Workflow, log_step
from shared.clients.blob_client import AzureBlobStorageClient as BlobStorageClient

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Temp workspace
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def _temp_workspace() -> Generator[tuple[Path, Path], None, None]:
    """Yield (src_dir, ocr_dir) inside a managed temp folder, cleaned up on exit."""
    base = Path(tempfile.mkdtemp(prefix="ocr_pipeline_"))
    src_dir = base / "source"
    ocr_dir = base / "output"
    src_dir.mkdir()
    ocr_dir.mkdir()
    logger.debug("Temp workspace: %s", base)
    try:
        yield src_dir, ocr_dir
    finally:
        try:
            shutil.rmtree(base)
            logger.debug("Cleaned temp workspace: %s", base)
        except Exception as exc:
            logger.warning("Temp cleanup failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Blob helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_blob_name(name: str) -> str:
    """Replace spaces and hyphens with underscores for consistent naming."""
    return name.replace(" ", "_").replace("-", "_")


def _get_blobs_in_lookback(container_client, lookback_hours: float) -> dict[str, object]:
    """Return {blob_name: BlobProperties} for PDFs modified within lookback_hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    return {
        b.name: b
        for b in container_client.list_blobs()
        if b.name.lower().endswith(".pdf")
        and b.last_modified
        and b.last_modified >= cutoff
    }


def _get_unprocessed_today(source_client, target_client) -> dict[str, object]:
    """
    Reconciliation: return today's source blobs that have no corresponding
    target blob (handles names with any _ocr / _enhanced_ocr suffix).
    """
    today = datetime.now(timezone.utc).date()

    source = {
        b.name: b
        for b in source_client.list_blobs()
        if b.name.lower().endswith(".pdf")
        and b.last_modified
        and b.last_modified.date() == today
    }

    existing_stems = {
        re.sub(r"(_enhanced)?_ocr$", "", Path(b.name).stem.lower())
        for b in target_client.list_blobs()
        if b.name.lower().endswith(".pdf")
        and b.last_modified
        and b.last_modified.date() == today
    }

    return {
        name: blob
        for name, blob in source.items()
        if Path(name).stem.lower() not in existing_stems
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF image enhancement
# ─────────────────────────────────────────────────────────────────────────────

def _pdf_to_images(pdf_path: Path, dpi: int = 300) -> list[Image.Image]:
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return images


def _enhance_page(pil_image: Image.Image) -> Image.Image:
    img = np.array(pil_image)

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )
    gray = clahe.apply(gray)

    gamma = 0.7
    inv_gamma = 1.0 / gamma

    table = np.array(
        [((i / 255.0) ** inv_gamma) * 255 for i in range(256)]
    ).astype("uint8")

    enhanced = cv2.LUT(gray, table)

    return Image.fromarray(enhanced)


def _enhance_pdf(
    input_pdf: Path,
    output_pdf: Path,
    dpi: int = 300,
) -> None:
    """
    Convert PDF → images → enhance → rebuild PDF.

    Avoids Pillow PDF writer completely.
    Works reliably in Azure Functions.
    """

    pages = _pdf_to_images(input_pdf, dpi=dpi)

    output_doc = fitz.open()

    temp_files = []

    try:
        for page_img in pages:

            enhanced = _enhance_page(page_img)

            tmp = tempfile.NamedTemporaryFile(
                suffix=".png",
                delete=False,
            )

            temp_path = Path(tmp.name)
            tmp.close()

            enhanced.save(temp_path)

            temp_files.append(temp_path)

            img_doc = fitz.open(str(temp_path))

            rect = img_doc[0].rect

            page = output_doc.new_page(
                width=rect.width,
                height=rect.height,
            )

            page.insert_image(
                page.rect,
                filename=str(temp_path),
            )

            img_doc.close()

        output_doc.save(str(output_pdf))

        logger.info(
            "Enhanced PDF saved: %s",
            output_pdf.name,
        )

    finally:
        output_doc.close()

        for f in temp_files:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

def _run_ocr(input_pdf: Path, output_pdf: Path) -> None:
    logger.info("Running OCR: %s", input_pdf.name)

    ocrmypdf.ocr(
        str(input_pdf),
        str(output_pdf),
        language="eng+jpn+tur",
        force_ocr=True,
        progress_bar=False,
        jobs=1,
    )

    logger.info("OCR done: %s", output_pdf.name)

# ─────────────────────────────────────────────────────────────────────────────
# Amount integrity check
# ─────────────────────────────────────────────────────────────────────────────

def _extract_numbers(pdf_path: Path) -> list[str]:
    text = extract_text(str(pdf_path))
    return re.findall(r"\b\d{1,3}(?:[ ,]\d{3})*(?:\.\d+)?\b", text)


def _normalize_numbers(numbers: list[str]) -> set[str]:
    return {re.sub(r"[ ,]", "", n) for n in numbers}


def _amounts_missing(original: list[str], ocr_result: list[str], threshold: float = 0.2) -> bool:
    if not original:
        return False
    orig_set = _normalize_numbers(original)
    ocr_set  = _normalize_numbers(ocr_result)
    ratio = len(orig_set - ocr_set) / len(orig_set)
    logger.info(
        "Amount check — original: %d  ocr: %d  missing: %.1f%%",
        len(orig_set), len(ocr_set), ratio * 100,
    )
    return ratio >= threshold


# ─────────────────────────────────────────────────────────────────────────────
# Per-file processing paths
# ─────────────────────────────────────────────────────────────────────────────

def _process_force_image(src_pdf: Path, ocr_dir: Path) -> Path:
    """Enhance → OCR. Always uses image-based path regardless of existing text layer."""
    enhanced = ocr_dir / f"{src_pdf.stem}_enhanced.pdf"
    result   = ocr_dir / f"{src_pdf.stem}_enhanced_ocr.pdf"
    _enhance_pdf(src_pdf, enhanced)
    _run_ocr(enhanced, result)
    return result


def _process_normal(src_pdf: Path, ocr_dir: Path) -> Path:
    """Direct OCR with amount integrity check; raises ValueError on mismatch."""
    result = ocr_dir / f"{src_pdf.stem}_ocr.pdf"
    orig_numbers = _extract_numbers(src_pdf)
    _run_ocr(src_pdf, result)
    ocr_numbers = _extract_numbers(result)
    if _amounts_missing(orig_numbers, ocr_numbers):
        raise ValueError("AMOUNT_MISMATCH — falling back to enhanced path")
    return result


def _process_with_fallback(src_pdf: Path, ocr_dir: Path) -> Path:
    """Try normal OCR; fall back to enhancement if it fails."""
    try:
        return _process_normal(src_pdf, ocr_dir)
    except Exception as exc:
        logger.warning("Normal OCR failed (%s) — trying image enhancement.", exc)
        return _process_force_image(src_pdf, ocr_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def process_files(
    lookback_hours: float = 0.5,
    force_img_processing: bool = True,
    run_id: str | None = None,
    source_container: str | None = None,
    target_container: str | None = None,
    failed_container: str | None = None,
) -> None:
    """
    Main OCR pipeline entry point.

    Parameters
    ----------
    lookback_hours      : How far back to scan the source container.
    force_img_processing: If True, always enhance + OCR regardless of existing
                          text layer. If False, try direct OCR first with an
                          amount-integrity fallback.
    run_id              : Workflow run ID for lineage tracking.
    source_container    : Override for source container name.
    target_container    : Override for target (OCR output) container name.
    failed_container    : Override for failed files container name.
    """
    _run_id  = run_id or f"ocr-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    src_cont = source_container or settings.source_container
    tgt_cont = target_container or settings.ocr_target_container
    fld_cont = failed_container or settings.ocr_failed_container

    logger.info("OCR pipeline starting. Run ID: %s", _run_id)

    blob = BlobStorageClient()
    source_client = blob.container(src_cont)
    target_client = blob.container(tgt_cont)

    # ── 1. Lookback window ────────────────────────────────────────────────────
    files = _get_blobs_in_lookback(source_client, lookback_hours)

    # ── 2. Reconciliation if nothing found in lookback ────────────────────────
    if not files:
        logger.info("No files in lookback window — running today reconciliation.")
        files = _get_unprocessed_today(source_client, target_client)

    if not files:
        logger.info("No files to process. Exiting OCR pipeline.")
        return

    logger.info("Processing %d file(s).", len(files))

    with _temp_workspace() as (src_dir, ocr_dir):
        for blob_name, _blob_props in files.items():
            src_pdf = src_dir / blob_name
            try:
                # Download
                src_pdf.parent.mkdir(parents=True, exist_ok=True)
                raw = blob.download_bytes(src_cont, blob_name)
                src_pdf.write_bytes(raw)
                logger.info("Downloaded: %s (%d bytes)", blob_name, len(raw))

                # Process
                if force_img_processing:
                    result_pdf = _process_force_image(src_pdf, ocr_dir)
                else:
                    result_pdf = _process_with_fallback(src_pdf, ocr_dir)

                # Upload to target
                target_name = _normalize_blob_name(result_pdf.name)
                blob.upload_file(tgt_cont, target_name, str(result_pdf))

                log_step(
                    run_id=_run_id,
                    workflow_name=Workflow.OCR_PIPELINE,
                    step_name=Step.OCR_COMPLETED,
                    status="Completed",
                    step_value=blob_name,
                    detail=f"Output: {target_name}",
                )
                logger.info("✓ %s → %s / %s", blob_name, tgt_cont, target_name)

            except Exception as exc:
                logger.error("✗ Fatal error processing %s: %s", blob_name, exc, exc_info=True)

                # Best-effort: stash original in failed container
                try:
                    if src_pdf.exists():
                        blob.upload_file(fld_cont, _normalize_blob_name(blob_name), str(src_pdf))
                except Exception as upload_exc:
                    logger.error("Failed to upload to failed container: %s", upload_exc)

                log_step(
                    run_id=_run_id,
                    workflow_name=Workflow.OCR_PIPELINE,
                    step_name=Step.OCR_FAILED,
                    status="Failed",
                    step_value=blob_name,
                    detail=str(exc),
                )

    log_step(
        run_id=_run_id,
        workflow_name=Workflow.OCR_PIPELINE,
        step_name=Step.WORKFLOW_COMPLETED,
        status="Completed",
        detail=f"Processed {len(files)} file(s).",
    )
    logger.info("OCR pipeline complete. Run ID: %s", _run_id)
