#!/usr/bin/env python3
"""
毎朝、最新のAIニュースをRSSで集めてGeminiで要約し、Slackに送るスクリプト。

GitHub Actions から毎朝自動実行される想定。
必要な環境変数（GitHub Secrets で設定）:
  - GEMINI_API_KEY      : Google AI Studio で取得したGeminiのAPIキー
  - SLACK_WEBHOOK_URL   : Slackの Incoming Webhook URL（送信先チャンネルに紐づく）
"""

import os
import sys
import html
import datetime
import json
import re
import time
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

# 最終的にSlackに届ける記事数
TARGET_ARTICLE_COUNT = 5

# Geminiのモデル。無料枠で使える 2.5 Flash を使用（2.0 Flashは2026年3月に廃止済み）
GEMINI_MODEL = "gemini-2.5-flash"

# 送信済みURLの保存先。古いものから切り捨て、直近300件だけ保持する。
SENT_FILE = "sent.json"
MAX_SENT_URLS = 300
RETRY_DELAYS = (2, 4, 8)


# ---- 送信済みURL --------------------------------------------------------

def load_sent_urls():
    """sent.json から送信済みURLを読み込む。壊れていても空扱いで続行する。"""
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        print(f"[warn] {SENT_FILE} の読み込みに失敗: {e}", file=sys.stderr)
        return []

    if not isinstance(data, list):
        print(f"[warn] {SENT_FILE} が配列ではないため空扱いにします", file=sys.stderr)
        return []
    return [url for url in data if isinstance(url, str) and url]


def save_sent_urls(urls):
    """送信済みURLを重複排除し、直近 MAX_SENT_URLS 件だけ保存する。"""
    unique_urls = list(dict.fromkeys(urls))
    trimmed_urls = unique_urls[-MAX_SENT_URLS:]
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed_urls, f, ensure_ascii=False, indent=2)
        f.write("\n")


def record_sent_urls(urls):
    """実際にSlackへ送った記事URLだけを sent.json に追記する。"""
    if not urls:
        return
    save_sent_urls(load_sent_urls() + urls)

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
    sent_urls = set(load_sent_urls())
    blocks = []
    article_id_to_url = {}
    fallback_articles = []
    next_article_id = 1

    for name, url in RSS_FEEDS:
        items = fetch_rss_items(name, url)
        if not items:
            continue
        lines = [f"## {name}"]
        for title, link, desc in items:
            if not link or link in sent_urls:
                continue

            article_id = next_article_id
            next_article_id += 1
            article_id_to_url[article_id] = link
            fallback_articles.append({
                "id": article_id,
                "source": name,
                "title": title,
                "url": link,
            })

            lines.append(f"- ID: {article_id}")
            lines.append(f"  見出し: {title}")
            if desc:
                lines.append(f"  概要: {desc[:300]}")
            lines.append(f"  リンクURL: {link}")
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks), article_id_to_url, fallback_articles


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
        "【各記事の書き方】Slackに投稿するので、以下の書式に厳密に従ってください。\n"
        "1行目に見出しを *見出し* の形式で書く（前後をアスタリスク1つで囲む。"
        "その記事の要点が一目でわかる、20字程度の日本語見出し）。\n"
        "2行目以降に本文を4〜5文で書く。次の流れを意識する:\n"
        "  - 何が起きたか（誰が・何を発表/開発したか）を最初の一文で。\n"
        "  - それがなぜ重要か、私たちにどう関係するかを続けて説明。\n"
        "専門用語（例: LLM、エージェント、マルチモーダル、推論モデル等）が出てきたら、"
        "その都度かっこ書きで一言かみくだいて説明する。例:「LLM（大量の文章を学習した文章生成AI）」。"
        "ただし、かっこ書きの補足は初心者が知らない技術用語（例: LLM、エージェント、マルチモーダル、推論モデル）に限る。"
        "一般的な言葉に略称・読み仮名・言い換えをかっこ書きで足さない（×スーパーコンピューター（スパコン） → ○スーパーコンピューター）。"
        "補足は1記事あたり多くても1〜2個にとどめる。\n\n"
        "【全体のルール】\n"
        f"- ちょうど{TARGET_ARTICLE_COUNT}件にする。\n"
        "- 記事と記事の間は、半角ハイフン3つだけの行（---）で区切る。\n"
        "- 太字はSlack記法の *アスタリスク1つ* を使う（** ではない）。\n"
        "- 企業名・製品名・サービス名・機能名・人名などの固有名詞は、アルファベットの原綴りのまま書く。"
        "カタカナ表記や、かっこ書きのカタカナ読み仮名を付け足さないこと。"
        "（×Cowork（コワーク） → ○Cowork ／ ×Anthropic（アンソロピック） → ○Anthropic）\n"
        "- 各記事の最後に、その記事の元IDを『元記事ID: <番号>』という行で必ず出力する。\n"
        "- 前置きや結びの挨拶、全体のまとめは不要。記事だけを返す。\n"
        "- 専門的になりすぎず、中学生でも理解できる平易な言葉を使う。\n\n"
        f"--- ニュース一覧 ---\n{news_text}"
    )

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    last_error = None
    max_attempts = len(RETRY_DELAYS) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            res = requests.post(endpoint, headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                break
            if res.status_code == 429 or 500 <= res.status_code < 600:
                last_error = RuntimeError(f"Gemini API エラー {res.status_code}: {res.text[:500]}")
            else:
                raise RuntimeError(f"Gemini API エラー {res.status_code}: {res.text[:500]}")
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = e

        if attempt == max_attempts:
            raise RuntimeError(f"Gemini API のリトライにすべて失敗しました: {last_error}")

        delay = RETRY_DELAYS[attempt - 1]
        print(f"[warn] Gemini要約に失敗しました（再試行 {attempt}/{len(RETRY_DELAYS)}）。{delay}秒後に再試行します: {last_error}", file=sys.stderr)
        time.sleep(delay)

    data = res.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini の応答を解析できませんでした: {e} / {data}")


# ---- Slack送信 ----------------------------------------------------------

def build_fallback_summary(fallback_articles):
    """Gemini失敗時に、候補の見出しとリンクだけでSlackへ送る本文を作る。"""
    articles = fallback_articles[:TARGET_ARTICLE_COUNT]
    return "\n---\n".join(
        [
            f"*{article['title']}*\n"
            f"{article['source']} の記事です。要約生成に失敗したため、元記事をご確認ください。\n"
            f"元記事ID: {article['id']}"
            for article in articles
        ]
    )


def prepare_article_for_slack(article, article_id_to_url):
    """Geminiが出した元記事ID行をSlack用リンクに差し替える。"""
    match = re.search(r"(?m)^元記事ID:\s*(\d+)\s*$", article)
    if not match:
        return article, None

    article_id = int(match.group(1))
    url = article_id_to_url.get(article_id)
    if not url:
        return article, None

    text = re.sub(r"(?m)^元記事ID:\s*\d+\s*$", f"<{url}|🔗 元記事を読む>", article).strip()
    return text, url

def build_slack_blocks(summary, today, article_id_to_url=None):
    """要約テキストをSlackのBlock Kit形式に整形する。

    Geminiが '---' 区切りで記事を返す前提で、記事ごとにセクションを分け、
    間に区切り線(divider)を入れて見やすくする。
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🤖 今日のAIニュース ({today})", "emoji": True},
        },
        {"type": "divider"},
    ]

    # '---' で記事を分割（前後の空白を除去し、空の塊は捨てる）
    article_id_to_url = article_id_to_url or {}
    sent_urls = []
    articles = [a.strip() for a in summary.split("---") if a.strip()]
    for i, article in enumerate(articles):
        article, sent_url = prepare_article_for_slack(article, article_id_to_url)
        if sent_url:
            sent_urls.append(sent_url)
        # Slackのsectionテキストは3000字まで。安全側で切り詰める。
        text = article[:2900]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        })
        # 最後の記事以外は区切り線を入れる
        if i < len(articles) - 1:
            blocks.append({"type": "divider"})

    return blocks, sent_urls


def send_to_slack(summary, webhook_url, today, article_id_to_url=None):
    """Slackの Incoming Webhook にメッセージを送る。"""
    blocks, sent_urls = build_slack_blocks(summary, today, article_id_to_url)
    payload = {
        # blocksが表示できない環境向けのフォールバックテキスト
        "text": f"🤖 今日のAIニュース ({today})",
        "blocks": blocks,
    }

    res = requests.post(webhook_url, json=payload, timeout=30)
    # Slack Webhookは成功時に本文 "ok" / ステータス200 を返す
    if res.status_code != 200 or res.text != "ok":
        raise RuntimeError(f"Slack 送信エラー {res.status_code}: {res.text[:500]}")
    return sent_urls


def send_plain_message_to_slack(message, webhook_url):
    """致命的な失敗時などに、Slackへ1行通知を送る。"""
    payload = {"text": message}
    res = requests.post(webhook_url, json=payload, timeout=30)
    if res.status_code != 200 or res.text != "ok":
        raise RuntimeError(f"Slack 送信エラー {res.status_code}: {res.text[:500]}")


# ---- メイン -------------------------------------------------------------

def main():
    gemini_key = os.environ.get("GEMINI_API_KEY")
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")

    missing = [
        name for name, val in [
            ("GEMINI_API_KEY", gemini_key),
            ("SLACK_WEBHOOK_URL", slack_webhook),
        ] if not val
    ]
    if missing:
        print(f"[error] 環境変数が未設定です: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today().strftime("%Y/%m/%d")
    try:
        print("ニュースを取得中...")
        news_text, article_id_to_url, fallback_articles = collect_news()
        if not news_text:
            print("[warn] ニュースを1件も取得できませんでした", file=sys.stderr)
            send_plain_message_to_slack("本日はニュースを取得できませんでした", slack_webhook)
            return

        try:
            print("Geminiで要約中...")
            summary = summarize_with_gemini(news_text, gemini_key)
        except Exception as e:
            print(f"[warn] Gemini要約に失敗したためフォールバックを送信します: {e}", file=sys.stderr)
            summary = build_fallback_summary(fallback_articles)

        print("Slackに送信中...")
        sent_urls = send_to_slack(summary, slack_webhook, today, article_id_to_url)
        record_sent_urls(sent_urls)
        print("完了！")
    except Exception as e:
        message = f"⚠️ 本日のAIニュース生成に失敗しました: {str(e)[:300]}"
        print(f"[error] {message}", file=sys.stderr)
        try:
            send_plain_message_to_slack(message, slack_webhook)
        except Exception as slack_error:
            print(f"[error] エラー通知のSlack送信にも失敗しました: {slack_error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
