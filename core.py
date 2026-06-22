#!/usr/bin/env python3
"""
Platform-neutral core logic for collecting AI news, asking Gemini for summaries,
tracking sent URLs, and converting Gemini output into Article objects.
"""

from dataclasses import dataclass
import datetime
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

import requests


# ---- 設定 --------------------------------------------------------------

RSS_FEEDS = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("ITmedia AI＋", "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml"),
]

MAX_ITEMS_PER_FEED = 6
TARGET_ARTICLE_COUNT = 5
GEMINI_MODEL = "gemini-2.5-flash"
SENT_FILE = "sent.json"
MAX_SENT_URLS = 300
RETRY_DELAYS = (2, 4, 8)
JST = datetime.timezone(datetime.timedelta(hours=9), "Asia/Tokyo")


@dataclass(frozen=True)
class Article:
    headline: str
    body: str
    url: str | None = None


def today_jst():
    return datetime.datetime.now(JST).date()


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
    """実際に通知できた記事URLだけを sent.json に追記する。"""
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

    channel_items = root.findall(".//item")
    if not channel_items:
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
    """Gemini API にニュース一覧を渡して素データ形式で要約してもらう。"""
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent"
    )
    today = today_jst().strftime("%Y年%m月%d日")
    prompt = (
        f"あなたは、AIに詳しくない初心者に向けて記事を書く新聞記者です。\n"
        f"以下は{today}に各メディア（海外・日本）が報じたAI関連ニュースの見出しと概要の一覧です。\n"
        "（英語の見出し・概要が含まれますが、日本語で書いてください。）\n\n"
        f"この中から特に重要・話題性の高いものを{TARGET_ARTICLE_COUNT}件選び、"
        "新聞記事のように、初心者にもわかりやすく要約してください。\n\n"
        "【各記事の書き方】以下の書式に厳密に従ってください。\n"
        "1行目に見出しを書く（装飾記号なし。その記事の要点が一目でわかる、20字程度の平易な日本語見出し）。\n"
        "2行目以降に本文を4〜5文で書く。次の流れを意識する:\n"
        "  - 何が起きたか（誰が・何を発表/開発したか）を最初の一文で。\n"
        "  - それがなぜ重要か、私たちにどう関係するかを続けて説明。\n"
        "最後の行に、その記事の元IDを『元記事ID: <番号>』という行で必ず書く。\n"
        "専門用語（例: LLM、エージェント、マルチモーダル、推論モデル等）が出てきたら、"
        "初出時にかっこ書きで一言かみくだいて説明する。例:「LLM（大量の文章を学習した文章生成AI）」。"
        "ただし、かっこ書きの補足は初心者が知らない技術用語（例: LLM、エージェント、マルチモーダル、推論モデル）に限る。"
        "一般的な言葉に略称・読み仮名・言い換えをかっこ書きで足さない（×スーパーコンピューター（スパコン） → ○スーパーコンピューター）。"
        "補足は1記事あたり多くても1〜2個にとどめる。\n\n"
        "【全体のルール】\n"
        f"- ちょうど{TARGET_ARTICLE_COUNT}件にする。\n"
        "- 記事と記事の間は、半角ハイフン3つだけの行（---）で区切る。\n"
        "- 企業名・製品名・サービス名・機能名・人名などの固有名詞は、アルファベットの原綴りのまま書く。"
        "カタカナ表記や、かっこ書きのカタカナ読み仮名を付け足さないこと。"
        "（×Cowork（コワーク） → ○Cowork ／ ×Anthropic（アンソロピック） → ○Anthropic）\n"
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


def parse_articles(summary_text, article_id_to_url):
    """Geminiの素データ出力を Article のリストに変換する。"""
    article_id_to_url = article_id_to_url or {}
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?m)^\s*---\s*$", summary_text)
        if chunk.strip()
    ]
    articles = []

    for chunk in chunks:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue

        headline = lines[0]
        body_lines = []
        url = None
        for line in lines[1:]:
            match = re.match(r"^元記事ID:\s*(\d+)\s*$", line)
            if match:
                url = article_id_to_url.get(int(match.group(1)))
                break
            body_lines.append(line)

        articles.append(Article(headline=headline, body="\n".join(body_lines).strip(), url=url))

    return articles


def build_fallback_articles(fallback_articles):
    """Gemini失敗時に、候補の見出しとリンクだけで Article のリストを作る。"""
    return [
        Article(
            headline=article["title"],
            body=f"{article['source']} の記事です。要約生成に失敗したため、元記事をご確認ください。",
            url=article.get("url"),
        )
        for article in fallback_articles[:TARGET_ARTICLE_COUNT]
    ]


def article_urls(articles):
    return [article.url for article in articles if article.url]
