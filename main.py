#!/usr/bin/env python3
"""
毎朝、最新のAIニュースをRSSで集めてGeminiで要約し、設定された通知先に送る入口。
"""

import os
import sys

from core import (
    already_sent_today,
    article_urls,
    build_fallback_articles,
    collect_news,
    mark_sent_today,
    parse_articles,
    record_sent_urls,
    summarize_with_gemini,
    today_jst,
)
from notifiers import get_notifiers


def configured_notifiers():
    notifiers = []
    for notifier in get_notifiers():
        name = notifier.__class__.__name__
        if notifier.is_configured():
            notifiers.append(notifier)
        else:
            print(f"[warn] {name} の環境変数が不足しているためスキップします", file=sys.stderr)
    return notifiers


def send_plain_to_all(notifiers, message):
    for notifier in notifiers:
        try:
            notifier.send_plain(message)
        except Exception as e:
            print(f"[error] {notifier.__class__.__name__} の通知送信に失敗しました: {e}", file=sys.stderr)


def send_articles_to_all(notifiers, articles, today):
    sent_count = 0
    for notifier in notifiers:
        try:
            notifier.send(articles, today)
            sent_count += 1
        except Exception as e:
            print(f"[error] {notifier.__class__.__name__} のニュース送信に失敗しました: {e}", file=sys.stderr)
    return sent_count


def is_schedule_event():
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def main():
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("[error] 環境変数が未設定です: GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    notifiers = configured_notifiers()
    if not notifiers:
        print("[error] 有効な通知先がありません", file=sys.stderr)
        sys.exit(1)

    today = today_jst().strftime("%Y/%m/%d")
    if is_schedule_event() and already_sent_today(today):
        print(f"[warn] {today} はすでに送信済みのためschedule実行をスキップします", file=sys.stderr)
        return

    try:
        print("ニュースを取得中...")
        news_text, article_id_to_url, fallback_candidates = collect_news()
        if not news_text:
            print("[warn] ニュースを1件も取得できませんでした", file=sys.stderr)
            send_plain_to_all(notifiers, "本日はニュースを取得できませんでした")
            return

        try:
            print("Geminiで要約中...")
            summary = summarize_with_gemini(news_text, gemini_key)
            articles = parse_articles(summary, article_id_to_url)
            if not articles:
                raise RuntimeError("Gemini の要約から記事を解析できませんでした")
            if len(article_urls(articles)) != len(articles):
                raise RuntimeError("Gemini の要約から元記事URLを解決できない記事がありました")
            gemini_summary_succeeded = True
        except Exception as e:
            print(f"[warn] Gemini要約に失敗したためフォールバックを送信します: {e}", file=sys.stderr)
            articles = build_fallback_articles(fallback_candidates)
            gemini_summary_succeeded = False

        print("通知先に送信中...")
        sent_count = send_articles_to_all(notifiers, articles, today)
        if sent_count == 0:
            raise RuntimeError("すべての通知先への送信に失敗しました")

        if gemini_summary_succeeded:
            record_sent_urls(article_urls(articles))
        if is_schedule_event():
            mark_sent_today(today)
        print("完了！")
    except Exception as e:
        message = f"⚠️ 本日のAIニュース生成に失敗しました: {str(e)[:300]}"
        print(f"[error] {message}", file=sys.stderr)
        send_plain_to_all(notifiers, message)
        sys.exit(1)


if __name__ == "__main__":
    main()
