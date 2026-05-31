"""
shared/utils/blob_naming.py
────────────────────────────
Centralises all file-naming logic.

Rules
─────
Source  : invoice_tr.pdf           (may have lang suffix)
Target doc  : invoice_en.pdf       (lang suffix replaced with _en)
Target JSON : invoice_en.json

If no lang suffix is present:
Source  : invoice.pdf
Target doc  : invoice_en.pdf
Target JSON : invoice_en.json

Email scanner raw-invoice output:
Source filename : invoice.pdf  + detected lang 'tr'
Stored as       : invoice_tr.pdf
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

# Matches a trailing _XX where XX is exactly 2 ASCII letters
_LANG_SUFFIX_RE = re.compile(r"_([a-zA-Z]{2})$")


def extract_source_lang(blob_name: str) -> str | None:
    """
    Extract a 2-character BCP-47 language code from the blob filename stem.

    >>> extract_source_lang("invoice_tr.pdf")
    'tr'
    >>> extract_source_lang("invoice.pdf")   # no suffix → None
    >>> extract_source_lang("invoice_abc.pdf")  # 3 chars → None
    """
    stem = PurePosixPath(blob_name).stem
    match = _LANG_SUFFIX_RE.search(stem)
    return match.group(1).lower() if match else None


def _clean_stem(blob_name: str) -> str:
    """Return the stem with any _XX lang suffix stripped."""
    stem = PurePosixPath(blob_name).stem
    return _LANG_SUFFIX_RE.sub("", stem)


def translated_blob_name(source_blob_name: str) -> str:
    """
    Target path for the translated document.

    invoice_tr.pdf  → invoice_en.pdf
    invoice.pdf     → invoice_en.pdf
    sub/doc_zh.pdf  → sub/doc_en.pdf

    >>> translated_blob_name("invoice_tr.pdf")
    'invoice_en.pdf'
    >>> translated_blob_name("invoice.pdf")
    'invoice_en.pdf'
    """
    p = PurePosixPath(source_blob_name)
    clean = _clean_stem(source_blob_name)
    return str(p.with_name(clean + "_en" + p.suffix))


def json_blob_name(source_blob_name: str) -> str:
    """
    Target path for the extracted JSON.

    invoice_tr.pdf  → invoice_en.json
    invoice.pdf     → invoice_en.json

    >>> json_blob_name("invoice_tr.pdf")
    'invoice_en.json'
    """
    p = PurePosixPath(source_blob_name)
    clean = _clean_stem(source_blob_name)
    return str(p.with_name(clean + "_en.json"))


def raw_invoice_blob_name(filename: str, lang_code: str) -> str:
    """
    Name for a valid invoice stored by the email scanner.

    invoice.pdf + 'tr' → invoice_tr.pdf

    >>> raw_invoice_blob_name("invoice.pdf", "tr")
    'invoice_tr.pdf'
    """
    p = PurePosixPath(filename)
    clean = _clean_stem(filename)  # remove any existing lang suffix
    return str(p.with_name(clean + f"_{lang_code}" + p.suffix))
