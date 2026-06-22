import os

import requests

from .discord import split_text_units


def format_line_article(article):
    lines = [f"【{article.headline}】"]
    if article.body:
        lines.append(article.body)
    if article.url:
        lines.append(f"🔗 {article.url}")
    return "\n".join(lines)


def build_line_chunks(articles, today, limit=5000):
    header = f"🤖 今日のAIニュース ({today})"
    units = [header] + [format_line_article(article) for article in articles]
    return split_text_units(units, limit, separator="\n\n")


class LineNotifier:
    def __init__(self, channel_token=None, user_id=None):
        self.channel_token = channel_token or os.environ.get("LINE_CHANNEL_TOKEN")
        self.user_id = user_id if user_id is not None else os.environ.get("LINE_USER_ID")

    def is_configured(self):
        return bool(self.channel_token)

    def _endpoint(self):
        if self.user_id:
            return "https://api.line.me/v2/bot/message/push"
        return "https://api.line.me/v2/bot/message/broadcast"

    def _payload(self, text):
        messages = [{"type": "text", "text": text}]
        if self.user_id:
            return {"to": self.user_id, "messages": messages}
        return {"messages": messages}

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_token}",
        }

    def send(self, articles, today):
        for chunk in build_line_chunks(articles, today):
            res = requests.post(self._endpoint(), headers=self._headers(), json=self._payload(chunk), timeout=30)
            if res.status_code != 200:
                raise RuntimeError(f"LINE API エラー {res.status_code}: {res.text[:500]}")

    def send_plain(self, message):
        res = requests.post(self._endpoint(), headers=self._headers(), json=self._payload(message[:5000]), timeout=30)
        if res.status_code != 200:
            raise RuntimeError(f"LINE API エラー {res.status_code}: {res.text[:500]}")
