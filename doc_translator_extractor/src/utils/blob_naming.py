"""
src/utils/blob_naming.py
─────────────────────────
Centralises all file-naming logic so it cannot drift between modules.

Rules
─────
Source container : <stem>.<ext>              e.g.  invoice-001.pdf
Target container : <stem>_en.<ext>           e.g.  invoice-001_en.pdf
Target container : <stem>_en.json            e.g.  invoice-001_en.json
"""

from __future__ import annotations

from __future__ import annotations

import re
from pathlib import PurePosixPath


# Matches a trailing _XX suffix where XX is exactly 2 ASCII letters
# e.g. "invoice_tr", "demo-invoice-20tax-7_zh"
_LANG_SUFFIX_RE = re.compile(r"_([a-zA-Z]{2})$")


def extract_source_lang(blob_name: str) -> str | None:
    """
    Attempt to extract the source language code from the blob filename.

    Convention: <stem>_<lang>.<ext>  e.g. invoice_tr.pdf → 'tr'

    Returns the 2-character BCP-47 language code (lowercased) if found,
    or None if the filename does not follow the convention.

    >>> extract_source_lang("invoice_tr.pdf")
    'tr'
    >>> extract_source_lang("demo-invoice-20tax-7_zh.pdf")
    'zh'
    >>> extract_source_lang("invoice.pdf")   # no lang suffix
    >>> extract_source_lang("invoice_abc.pdf")  # 3 chars — not a lang code
    """
    stem = PurePosixPath(blob_name).stem  # e.g. "invoice_tr"
    match = _LANG_SUFFIX_RE.search(stem)
    if match:
        return match.group(1).lower()
    return None


def translated_blob_name(source_blob_name: str) -> str:
    """
    Return the target blob name for the translated document.

    >>> translated_blob_name("folder/invoice-001.pdf")
    'folder/invoice-001_en.pdf'
    """
    p = PurePosixPath(source_blob_name)
    return str(p.with_name(p.stem + "_en" + p.suffix))


def json_blob_name(source_blob_name: str) -> str:
    """
    Return the target blob name for the extracted-data JSON.

    >>> json_blob_name("folder/invoice-001.pdf")
    'folder/invoice-001_en.json'
    """
    p = PurePosixPath(source_blob_name)
    return str(p.with_name(p.stem + "_en.json"))
