"""
workflows/email_scanner/services/language_detector.py
───────────────────────────────────────────────────────
Uses the Azure Translator detect endpoint to get the BCP-47 language code
from a text sample, returning the 2-character code used in blob naming.
"""
from __future__ import annotations

import logging

import requests

from config.settings import settings
from shared.utils.retry import retry

logger = logging.getLogger(__name__)

_DETECT_ENDPOINT = "https://api.cognitive.microsofttranslator.com/detect"


class LanguageDetector:
    def __init__(self) -> None:
        self._key = settings.translator_key
        self._region = settings.translator_region

    @retry(max_attempts=3, base_delay=1.0, exceptions=(requests.HTTPError, Exception))
    def detect(self, text: str) -> str | None:
        """
        Detect the language of *text*.

        Returns
        -------
        str  : 2-character BCP-47 language code (e.g. 'tr', 'zh', 'de')
               or None if detection fails or confidence is too low.
        """
        if not text or not text.strip():
            return None

        resp = requests.post(
            _DETECT_ENDPOINT,
            params={"api-version": "3.0"},
            headers={
                "Ocp-Apim-Subscription-Key": self._key,
                "Ocp-Apim-Subscription-Region": self._region,
                "Content-Type": "application/json",
            },
            # Use first 500 chars — enough for reliable detection
            json=[{"text": text[:500]}],
            timeout=15,
        )
        resp.raise_for_status()

        result = resp.json()
        if not result:
            return None

        entry = result[0]
        language = entry.get("language", "")
        score = entry.get("score", 0.0)

        # Only accept if the code is exactly 2 chars and confidence is reasonable
        if len(language) == 2 and score >= 0.5:
            logger.info("Detected language: %s (score=%.2f)", language, score)
            return language.lower()

        # Some codes are longer (e.g. zh-Hans) — take the prefix
        if "-" in language and score >= 0.5:
            short = language.split("-")[0].lower()
            if len(short) == 2:
                logger.info(
                    "Detected language (trimmed): %s → %s (score=%.2f)",
                    language,
                    short,
                    score,
                )
                return short

        logger.warning(
            "Language detection uncertain: lang=%s score=%.2f — will use 'xx'",
            language,
            score,
        )
        return None
