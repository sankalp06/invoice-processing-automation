"""
tests/test_blob_naming.py
──────────────────────────
Unit tests for naming convention helpers — no Azure calls needed.
"""

import pytest
from src.utils.blob_naming import extract_source_lang, json_blob_name, translated_blob_name


@pytest.mark.parametrize(
    "source, expected_doc, expected_json",
    [
        ("invoice.pdf",         "invoice_en.pdf",         "invoice_en.json"),
        ("invoice.PDF",         "invoice_en.PDF",         "invoice_en.json"),
        ("sub/invoice.pdf",     "sub/invoice_en.pdf",     "sub/invoice_en.json"),
        ("a/b/c/doc.docx",      "a/b/c/doc_en.docx",      "a/b/c/doc_en.json"),
        ("no-ext",              "no-ext_en",              "no-ext_en.json"),
        ("file.name.with.dots.pdf", "file.name.with.dots_en.pdf", "file.name.with.dots_en.json"),
    ],
)
def test_translated_blob_name(source, expected_doc, expected_json):
    assert translated_blob_name(source) == expected_doc
    assert json_blob_name(source) == expected_json


@pytest.mark.parametrize(
    "blob_name, expected_lang",
    [
        ("invoice_tr.pdf",               "tr"),   # Turkish
        ("invoice_zh.pdf",               "zh"),   # Chinese
        ("invoice_JA.pdf",               "ja"),   # Japanese — uppercased, normalised
        ("demo-invoice-20tax-7_fr.pdf",  "fr"),   # hyphenated stem
        ("sub/folder/doc_de.docx",       "de"),   # nested path
        ("invoice.pdf",                  None),   # no suffix
        ("invoice_abc.pdf",              None),   # 3-char — not a lang code
        ("invoice_1x.pdf",               None),   # digit — not a lang code
        ("invoice_t.pdf",                None),   # 1-char — not a lang code
        ("invoice_en.pdf",               "en"),   # already English, still extracted
        ("no-ext",                       None),   # no extension, no suffix
    ],
)
def test_extract_source_lang(blob_name, expected_lang):
    assert extract_source_lang(blob_name) == expected_lang
