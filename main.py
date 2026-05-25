#!/usr/bin/env python3
"""
毎朝、最新ニュースをRSSで集めてGeminiで要約し、LINEに送るスクリプト。

GitHub Actions から毎朝自動実行される想定。
必要な環境変数（GitHub Secrets で設定）:
  - GEMINI_API_KEY      : Google AI Studio で取得したGeminiのAPIキー
  - LINE_CHANNEL_TOKEN  : LINE Messaging API のチャネルアクセストークン
  - LINE_USER_ID        : 自分のLINEユーザーID（送信先）
"""

import os
import sys
import html
import datetime
import urllib.request
import xml.etree.ElementTree as ET

import requests

# ---- 設定 --------------------------------------------------------------

# 収集するRSSフィード（AI関連）。海外の最新AI情報＋日本語ソースを混ぜています。
# 好きなものに差し替え・追加してOK。
RSS_FEEDS = [
    # --- 海外（英語）---
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    # --- 日本語 ---
    ("ITmedia AI＋", "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml"),
]

# 各フィードから拾う最大記事数。Geminiが「全体から5件選ぶ」ので、
# 候補は多めに集めておく（その方が良いニュースを選びやすい）。
MAX_ITEMS_PER_FEED = 6

# 最終的にLINEに届ける記事数
TARGET_ARTICLE_COUNT = 5

# Geminiのモデル。無料枠で使える 2.5 Flash を使用（2.0 Flashは2026年3月に廃止済み）
GEMINI_MODEL = "gemini-2.5-flash"

# ---- RSS取得 ------------------------------------------------------------

def fetch_rss_items(name, url):
    """1つのRSSフィードから (タイトル, リンク, 概要) のリストを返す。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as res:
            data = res.read()
    except Exception as e:
        print(f"[warn] {name} の取得に失敗: {e}", file=sys.stderr)
        return []

    items = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"[warn] {name} の解析に失敗: {e}", file=sys.stderr)
        return []

    # RSS 2.0 の <item> を想定。Atom の場合は <entry>。
    channel_items = root.findall(".//item")
    if not channel_items:
        # Atom 形式へのフォールバック
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns)[:MAX_ITEMS_PER_FEED]:
            title = entry.findtext("atom:title", default="", namespaces=ns)
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            summary = entry.findtext("atom:summary", default="", namespaces=ns)
            items.append((title.strip(), link, summary.strip()))
        return items

    for item in channel_items[:MAX_ITEMS_PER_FEED]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        # description に HTML タグが混ざることがあるので簡易的に除去
        desc = html.unescape(desc)
        items.append((title, link, desc))
    return items


def collect_news():
    """全フィードをまとめて取得し、Geminiに渡すテキストを作る。"""
    blocks = []
    for name, url in RSS_FEEDS:
        items = fetch_rss_items(name, url)
        if not items:
            continue
        lines = [f"## {name}"]
        for title, link, desc in items:
            lines.append(f"- 見出し: {title}")
            if desc:
                lines.append(f"  概要: {desc[:300]}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---- Gemini要約 ---------------------------------------------------------

def summarize_with_gemini(news_text, api_key):
    """Gemini API にニュース一覧を渡して要約してもらう。"""
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent"
    )
    today = datetime.date.today().strftime("%Y年%m月%d日")
    prompt = (
        f"あなたは、AIに詳しくない初心者に向けて記事を書く新聞記者です。\n"
        f"以下は{today}に各メディア（海外・日本）が報じたAI関連ニュースの見出しと概要の一覧です。\n"
        "（英語の見出し・概要が含まれますが、日本語で書いてください。）\n\n"
        f"この中から特に重要・話題性の高いものを{TARGET_ARTICLE_COUNT}件選び、"
        "新聞記事のように、初心者にもわかりやすく要約してください。\n\n"
        "【各記事の書き方】\n"
        "1行目に【見出し】を書く（その記事の要点が一目でわかる、20字程度の日本語見出し）。\n"
        "続けて本文を4〜5文で書く。次の流れを意識する:\n"
        "  - 何が起きたか（誰が・何を発表/開発したか）を最初の一文で。\n"
        "  - それがなぜ重要か、私たちにどう関係するかを続けて説明。\n"
        "専門用語（例: LLM、エージェント、マルチモーダル、推論モデル等）が出てきたら、"
        "その都度かっこ書きで一言かみくだいて説明する。例:「LLM（大量の文章を学習した文章生成AI）」。\n\n"
        "【全体のルール】\n"
        f"- ちょうど{TARGET_ARTICLE_COUNT}件にする。\n"
        "- 記事と記事の間は空行1つで区切る。\n"
        "- 前置きや結びの挨拶、全体のまとめは不要。記事だけを返す。\n"
        "- 専門的になりすぎず、中学生でも理解できる平易な言葉を使う。\n\n"
        f"--- ニュース一覧 ---\n{news_text}"
    )

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    res = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    if res.status_code != 200:
        raise RuntimeError(f"Gemini API エラー {res.status_code}: {res.text[:500]}")

    data = res.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini の応答を解析できませんでした: {e} / {data}")


# ---- LINE送信 -----------------------------------------------------------

def send_to_line(message, channel_token, user_id):
    """LINE Messaging API の push でメッセージを送る。"""
    endpoint = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_token}",
    }
    # LINEの1メッセージは5000文字まで。安全側で切り詰める。
    text = message[:4900]
    payload = {"to": user_id, "messages": [{"type": "text", "text": text}]}

    res = requests.post(endpoint, headers=headers, json=payload, timeout=30)
    if res.status_code != 200:
        raise RuntimeError(f"LINE API エラー {res.status_code}: {res.text[:500]}")


# ---- メイン -------------------------------------------------------------

def main():
    gemini_key = os.environ.get("GEMINI_API_KEY")
    line_token = os.environ.get("LINE_CHANNEL_TOKEN")
    line_user = os.environ.get("LINE_USER_ID")

    missing = [
        name for name, val in [
            ("GEMINI_API_KEY", gemini_key),
            ("LINE_CHANNEL_TOKEN", line_token),
            ("LINE_USER_ID", line_user),
        ] if not val
    ]
    if missing:
        print(f"[error] 環境変数が未設定です: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    print("ニュースを取得中...")
    news_text = collect_news()
    if not news_text:
        print("[error] ニュースを1件も取得できませんでした", file=sys.stderr)
        sys.exit(1)

    print("Geminiで要約中...")
    summary = summarize_with_gemini(news_text, gemini_key)

    today = datetime.date.today().strftime("%Y/%m/%d")
    header = f"🤖 今日のAIニュース ({today})\n\n"
    message = header + summary

    print("LINEに送信中...")
    send_to_line(message, line_token, line_user)
    print("完了！")


if __name__ == "__main__":
    main()
