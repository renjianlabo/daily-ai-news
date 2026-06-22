import unittest

from core import Article, build_fallback_articles, parse_articles


class CoreArticleTests(unittest.TestCase):
    def test_parse_articles_extracts_headline_body_and_url(self):
        summary = """AI検索が広がる
OpenAIが新しい検索機能を発表しました。
利用者は情報を探しやすくなります。
元記事ID: 2
---
推論モデルが改善
Google DeepMindが新モデルを公開しました。
元記事ID: 9
"""

        articles = parse_articles(summary, {2: "https://example.com/a"})

        self.assertEqual(
            articles,
            [
                Article(
                    headline="AI検索が広がる",
                    body="OpenAIが新しい検索機能を発表しました。\n利用者は情報を探しやすくなります。",
                    url="https://example.com/a",
                ),
                Article(
                    headline="推論モデルが改善",
                    body="Google DeepMindが新モデルを公開しました。",
                    url=None,
                ),
            ],
        )

    def test_build_fallback_articles_returns_common_article_list(self):
        fallback_articles = [
            {"id": 1, "source": "TechCrunch AI", "title": "OpenAI releases tool", "url": "https://example.com/1"},
            {"id": 2, "source": "ITmedia AI+", "title": "国内AIニュース", "url": "https://example.com/2"},
        ]

        articles = build_fallback_articles(fallback_articles)

        self.assertEqual(articles[0].headline, "OpenAI releases tool")
        self.assertEqual(
            articles[0].body,
            "TechCrunch AI の記事です。要約生成に失敗したため、元記事をご確認ください。",
        )
        self.assertEqual(articles[0].url, "https://example.com/1")


if __name__ == "__main__":
    unittest.main()
