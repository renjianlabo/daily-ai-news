import os

import requests


def format_discord_article(article):
    lines = [f"**{article.headline}**"]
    if article.body:
        lines.append(article.body)
    if article.url:
        lines.append(f"🔗 元記事を読む: {article.url}")
    return "\n".join(lines)


def split_text_units(units, limit, separator="\n\n"):
    chunks = []
    current = ""

    for unit in units:
        candidate = unit if not current else current + separator + unit
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(unit) > limit:
            chunks.append(unit[:limit])
            unit = unit[limit:]
        current = unit

    if current:
        chunks.append(current)
    return chunks


def build_discord_chunks(articles, today, limit=2000):
    header = f"🤖 今日のAIニュース ({today})"
    units = [header] + [format_discord_article(article) for article in articles]
    return split_text_units(units, limit, separator="\n\n───\n\n")


class DiscordNotifier:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")

    def is_configured(self):
        return bool(self.webhook_url)

    def send(self, articles, today):
        for chunk in build_discord_chunks(articles, today):
            res = requests.post(self.webhook_url, json={"content": chunk}, timeout=30)
            if res.status_code not in (200, 204):
                raise RuntimeError(f"Discord 送信エラー {res.status_code}: {res.text[:500]}")

    def send_plain(self, message):
        res = requests.post(self.webhook_url, json={"content": message[:2000]}, timeout=30)
        if res.status_code not in (200, 204):
            raise RuntimeError(f"Discord 送信エラー {res.status_code}: {res.text[:500]}")
