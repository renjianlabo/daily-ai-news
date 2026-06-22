import os

import requests


def format_slack_article(article):
    lines = [f"*{article.headline}*"]
    if article.body:
        lines.append(article.body)
    if article.url:
        lines.append(f"<{article.url}|🔗 元記事を読む>")
    return "\n".join(lines)


def build_slack_blocks(articles, today):
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🤖 今日のAIニュース ({today})", "emoji": True},
        },
        {"type": "divider"},
    ]

    for i, article in enumerate(articles):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": format_slack_article(article)[:2900]},
        })
        if i < len(articles) - 1:
            blocks.append({"type": "divider"})

    return blocks


def build_slack_payload(articles, today):
    return {
        "text": f"🤖 今日のAIニュース ({today})",
        "blocks": build_slack_blocks(articles, today),
        "unfurl_links": False,
        "unfurl_media": False,
    }


class SlackNotifier:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")

    def is_configured(self):
        return bool(self.webhook_url)

    def send(self, articles, today):
        payload = build_slack_payload(articles, today)
        res = requests.post(self.webhook_url, json=payload, timeout=30)
        if res.status_code != 200 or res.text != "ok":
            raise RuntimeError(f"Slack 送信エラー {res.status_code}: {res.text[:500]}")

    def send_plain(self, message):
        payload = {
            "text": message,
            "unfurl_links": False,
            "unfurl_media": False,
        }
        res = requests.post(self.webhook_url, json=payload, timeout=30)
        if res.status_code != 200 or res.text != "ok":
            raise RuntimeError(f"Slack 送信エラー {res.status_code}: {res.text[:500]}")
