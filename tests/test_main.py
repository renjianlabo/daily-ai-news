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

    def test_schedule_run_skips_when_today_already_sent(self):
        notifier = DummyNotifier()

        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy", "GITHUB_EVENT_NAME": "schedule"}, clear=False), \
             patch.object(main, "configured_notifiers", return_value=[notifier]), \
             patch.object(main, "already_sent_today", return_value=True), \
             patch.object(main, "collect_news") as collect_news, \
             patch.object(main, "record_sent_urls") as record_sent_urls:
            main.main()

        collect_news.assert_not_called()
        record_sent_urls.assert_not_called()
        self.assertEqual(notifier.sent, [])

    def test_manual_run_does_not_use_same_day_schedule_guard(self):
        notifier = DummyNotifier()
        parsed_articles = [Article("Headline", "Body", "https://example.com/success")]

        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy", "GITHUB_EVENT_NAME": "workflow_dispatch"}, clear=False), \
             patch.object(main, "configured_notifiers", return_value=[notifier]), \
             patch.object(main, "already_sent_today", return_value=True) as already_sent_today, \
             patch.object(main, "collect_news", return_value=("news text", {1: "https://example.com/success"}, [])), \
             patch.object(main, "summarize_with_gemini", return_value="summary text"), \
             patch.object(main, "parse_articles", return_value=parsed_articles), \
             patch.object(main, "record_sent_urls"):
            main.main()

        already_sent_today.assert_not_called()
        self.assertEqual(len(notifier.sent), 1)

    def test_successful_schedule_run_marks_today_as_sent(self):
        notifier = DummyNotifier()
        parsed_articles = [Article("Headline", "Body", "https://example.com/success")]

        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy", "GITHUB_EVENT_NAME": "schedule"}, clear=False), \
             patch.object(main, "configured_notifiers", return_value=[notifier]), \
             patch.object(main, "already_sent_today", return_value=False), \
             patch.object(main, "collect_news", return_value=("news text", {1: "https://example.com/success"}, [])), \
             patch.object(main, "summarize_with_gemini", return_value="summary text"), \
             patch.object(main, "parse_articles", return_value=parsed_articles), \
             patch.object(main, "record_sent_urls"), \
             patch.object(main, "mark_sent_today") as mark_sent_today:
            main.main()

        mark_sent_today.assert_called_once()

    def test_articles_missing_urls_fall_back_and_do_not_record(self):
        notifier = DummyNotifier()
        fallback_articles = [
            {"id": 1, "source": "TechCrunch AI", "title": "Fallback title", "url": "https://example.com/fallback"},
        ]
        parsed_articles = [
            Article("No URL", "Body", None),
            Article("With URL", "Body", "https://example.com/success"),
        ]

        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy"}, clear=False), \
             patch.object(main, "configured_notifiers", return_value=[notifier]), \
             patch.object(main, "collect_news", return_value=("news text", {1: "https://example.com/fallback"}, fallback_articles)), \
             patch.object(main, "summarize_with_gemini", return_value="summary text"), \
             patch.object(main, "parse_articles", return_value=parsed_articles), \
             patch.object(main, "record_sent_urls") as record_sent_urls:
            main.main()

        self.assertEqual(notifier.sent[0][0][0].headline, "Fallback title")
        self.assertEqual(notifier.sent[0][0][0].url, "https://example.com/fallback")
        record_sent_urls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
