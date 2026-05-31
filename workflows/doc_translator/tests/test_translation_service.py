"""
tests/test_translation_service.py
───────────────────────────────────
Unit tests for TranslationService — mocks the Translator client.
"""

from unittest.mock import MagicMock, call

import pytest

from workflows.doc_translator.services.translation_service import TranslationService


def make_service(chunk_size: int = 20) -> tuple[TranslationService, MagicMock]:
    mock_client = MagicMock()
    mock_client.translate_text.side_effect = lambda text, source_lang=None: f"[EN]{text}"

    svc = TranslationService(translator_client=mock_client)
    svc._chunk_size = chunk_size  # override for testing
    return svc, mock_client


def test_empty_text_returns_empty():
    svc, client = make_service()
    assert svc.translate("") == ""
    client.translate_text.assert_not_called()


def test_single_chunk_no_split():
    svc, client = make_service(chunk_size=100)
    result = svc.translate("hello", source_lang="tr")
    assert result == "[EN]hello"
    client.translate_text.assert_called_once_with("hello", source_lang="tr")


def test_text_is_chunked():
    svc, client = make_service(chunk_size=5)
    # "1234567890" → ["12345", "67890"]
    result = svc.translate("1234567890")
    assert client.translate_text.call_count == 2
    assert result == "[EN]12345\n[EN]67890"


def test_fallback_to_auto_detect_on_error():
    mock_client = MagicMock()
    # First call (with source_lang) raises; second (auto) succeeds
    mock_client.translate_text.side_effect = [
        Exception("bad lang"),
        "translated",
    ]

    svc = TranslationService(translator_client=mock_client)
    svc._chunk_size = 100

    result = svc.translate("some text", source_lang="xx")
    assert result == "translated"
    assert mock_client.translate_text.call_count == 2


def test_no_fallback_when_already_auto():
    mock_client = MagicMock()
    mock_client.translate_text.side_effect = Exception("api error")

    svc = TranslationService(translator_client=mock_client)
    svc._chunk_size = 100

    with pytest.raises(Exception, match="api error"):
        svc.translate("some text", source_lang=None)
