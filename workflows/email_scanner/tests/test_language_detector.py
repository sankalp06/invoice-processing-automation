"""
Tests for LanguageDetector with mocked HTTP calls.
"""
from unittest.mock import MagicMock, patch
import pytest
from workflows.email_scanner.services.language_detector import LanguageDetector


def _mock_detect(language: str, score: float):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"language": language, "score": score}]
    mock_resp.raise_for_status.return_value = None
    return mock_resp


@patch("workflows.email_scanner.services.language_detector.requests.post")
def test_detects_turkish(mock_post):
    mock_post.return_value = _mock_detect("tr", 0.99)
    detector = LanguageDetector()
    assert detector.detect("Fatura numarası") == "tr"


@patch("workflows.email_scanner.services.language_detector.requests.post")
def test_trims_long_code(mock_post):
    mock_post.return_value = _mock_detect("zh-Hans", 0.95)
    detector = LanguageDetector()
    assert detector.detect("你好") == "zh"


@patch("workflows.email_scanner.services.language_detector.requests.post")
def test_low_confidence_returns_none(mock_post):
    mock_post.return_value = _mock_detect("tr", 0.2)
    detector = LanguageDetector()
    assert detector.detect("hello") is None


def test_empty_text_returns_none():
    detector = LanguageDetector()
    assert detector.detect("") is None
    assert detector.detect("   ") is None
