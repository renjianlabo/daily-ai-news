import os
import unittest
from unittest.mock import patch

import main
from core import Article


class DummyNotifier:
    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    def send(self, articles, today):
        self.sent.append((articles, today))

    def send_plain(self, message):
        self.sent.append(message)


class MainSentRecordingTests(unittest.TestCase):
    def test_fallback_send_does_not_record_sent_urls(self):
        notifier = DummyNotifier()
        fallback_articles = [
            {"id": 1, "source": "TechCrunch AI", "title": "Fallback title", "url": "https://example.com/fallback"},
        ]

        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy"}, clear=False), \
             patch.object(main, "configured_notifiers", return_value=[notifier]), \
             patch.object(main, "collect_news", return_value=("news text", {1: "https://example.com/fallback"}, fallback_articles)), \
             patch.object(main, "summarize_with_gemini", side_effect=RuntimeError("Gemini 503")), \
             patch.object(main, "record_sent_urls") as record_sent_urls:
            main.main()

        self.assertEqual(len(notifier.sent), 1)
        record_sent_urls.assert_not_called()

    def test_successful_gemini_summary_records_sent_urls_once(self):
        notifier = DummyNotifier()
        parsed_articles = [Article("Headline", "Body", "https://example.com/success")]

        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy"}, clear=False), \
             patch.object(main, "configured_notifiers", return_value=[notifier]), \
             patch.object(main, "collect_news", return_value=("news text", {1: "https://example.com/success"}, [])), \
             patch.object(main, "summarize_with_gemini", return_value="summary text"), \
             patch.object(main, "parse_articles", return_value=parsed_articles), \
             patch.object(main, "record_sent_urls") as record_sent_urls:
            main.main()

        record_sent_urls.assert_called_once_with(["https://example.com/success"])


if __name__ == "__main__":
    unittest.main()
