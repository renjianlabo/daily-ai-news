import unittest

from core import Article
from notifiers.discord import build_discord_chunks
from notifiers.line import build_line_chunks
from notifiers.slack import build_slack_blocks, build_slack_payload


class NotifierFormattingTests(unittest.TestCase):
    def test_slack_blocks_match_existing_shape_and_disable_unfurl(self):
        articles = [
            Article("AI検索が広がる", "本文1\n本文2", "https://example.com/a"),
            Article("推論モデルが改善", "本文3", None),
        ]

        blocks = build_slack_blocks(articles, "2026/06/23")
        payload = build_slack_payload(articles, "2026/06/23")

        self.assertEqual(blocks[0]["type"], "header")
        self.assertEqual(blocks[0]["text"]["text"], "🤖 今日のAIニュース (2026/06/23)")
        self.assertEqual(blocks[1], {"type": "divider"})
        self.assertEqual(blocks[2]["text"]["type"], "mrkdwn")
        self.assertEqual(
            blocks[2]["text"]["text"],
            "*AI検索が広がる*\n本文1\n本文2\n<https://example.com/a|🔗 元記事を読む>",
        )
        self.assertEqual(blocks[3], {"type": "divider"})
        self.assertEqual(blocks[4]["text"]["text"], "*推論モデルが改善*\n本文3")
        self.assertFalse(payload["unfurl_links"])
        self.assertFalse(payload["unfurl_media"])

    def test_discord_chunks_use_markdown_and_split_under_limit(self):
        articles = [
            Article("長いニュース", "あ" * 1950, "https://example.com/a"),
            Article("次のニュース", "短い本文", "https://example.com/b"),
        ]

        chunks = build_discord_chunks(articles, "2026/06/23", limit=2000)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))
        self.assertTrue(chunks[0].startswith("🤖 今日のAIニュース (2026/06/23)"))
        joined = "\n".join(chunks)
        self.assertIn("**長いニュース**", joined)
        self.assertIn("🔗 元記事を読む: https://example.com/a", joined)

    def test_line_chunks_use_plain_text_and_split_under_limit(self):
        articles = [
            Article("長いニュース", "あ" * 4950, "https://example.com/a"),
            Article("次のニュース", "短い本文", None),
        ]

        chunks = build_line_chunks(articles, "2026/06/23", limit=5000)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 5000 for chunk in chunks))
        self.assertTrue(chunks[0].startswith("🤖 今日のAIニュース (2026/06/23)"))
        joined = "\n".join(chunks)
        self.assertIn("【長いニュース】", joined)
        self.assertIn("🔗 https://example.com/a", joined)


if __name__ == "__main__":
    unittest.main()
