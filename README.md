# 毎朝AIニュースを自動で届けるbot（GitHub Actions × Gemini × Notifier）

海外・日本のAIメディアから最新ニュースを集め、Gemini で初心者向けに要約し、**毎朝 自動で Slack / Discord / LINE に届ける**botです。サーバーもPCの常時起動も不要で、GitHub のサーバー上だけで完結します。既定では Slack のみに投稿します。

> RSS収集 → 重複除外 → Gemini要約 → 共通記事データ化 → Notifier別整形 → 送信 → 送信済み記録、までを 1日1回・全自動・無料で回しています。

<img width="300" alt="Slackに届いたニュースまとめ" src="https://github.com/user-attachments/assets/d3b02ab2-10f6-41f1-89ef-d9e0af40603c" />

---

## できること

- 毎朝（日本時間 7時台）に、AI関連の注目ニュース5件を自動投稿
- `NOTIFY_TARGETS` で Slack / Discord / LINE の通知先を切り替え
- 英語記事も含めてすべて日本語で要約。専門用語には初心者向けのかみくだき解説つき
- 各記事に元記事へのリンク付き
- **同じニュースが翌日以降に重複して届かない**
- 一時的なエラーで「届かない日」が出ないよう、リトライとフォールバックを実装

---

## 設計のポイント（エンジニアリング上の判断）

このbotは「RSSを集めてAIで要約して通知する」だけなら数十行で書けますが、**毎日・自動・無人で安定運用する**ために、次の設計判断を入れています。

### 1. 使い捨て実行環境でも「記憶」を持たせる（重複排除）

GitHub Actions の実行環境は毎回まっさらに初期化されるため、普通に作ると「昨日何を送ったか」を覚えていられず、同じニュースが繰り返し届きます。
そこで、**実際に送信した記事のURLだけ**を `sent.json` に記録し、ジョブ実行後に Actions 自身がそのファイルをリポジトリへ commit して状態を保持します。翌日はこの記録を参照して既出記事を候補から除外。記録は直近300件で自動トリムし、肥大も防いでいます。

### 2. 「届かない日」をなくす障害耐性

外部APIは時々失敗します。

- Gemini呼び出しは、**一時的な失敗（レート制限429・サーバーエラー5xx・タイムアウト・接続断）だけ指数バックオフでリトライ**。
- リトライも全滅した場合は、要約を諦めて**見出し＋リンクの素のリストだけでも投稿**するフォールバックに切り替え。
- 致命的に失敗した場合は、黙って消えずに有効な通知先へエラー通知を出す。
- RSS取得は各フィードを個別に try/except し、1ソースが落ちても全体は止めない。

### 3. 素データ方式の Notifier パターン

Geminiには Slack / Discord / LINE に依存しない素データ形式で要約させ、`core.Article` のリストに変換します。各 Notifier は同じ記事リストを受け取り、自分のプラットフォームに合う書式で送信します。

- Slack: Block Kit。ヘッダー、section、divider、太字見出し、元記事リンク、unfurl無効を維持。
- Discord: Markdown本文。2000字を超える場合は複数メッセージに分割。
- LINE: プレーンテキスト。5000字を超える場合は分割。`LINE_USER_ID` があれば push、なければ broadcast。

### 4. タイムゾーンを正しく扱うスケジューリング

cron に `timezone: 'Asia/Tokyo'` を明示し、実行stepにも `TZ: 'Asia/Tokyo'` を指定。コード内の日付生成も JST 固定の `today_jst()` を使います。

---

## 技術スタック

| 領域 | 使用技術 |
| --- | --- |
| 言語 | Python 3.12 |
| 情報収集 | RSS（`urllib` / `xml.etree`）、`requests` |
| 要約 | Google Gemini API（`gemini-2.5-flash`） |
| 通知 | Slack Incoming Webhook / Discord Webhook / LINE Messaging API |
| 実行基盤 | GitHub Actions（cron スケジューリング・状態の自動コミット） |
| 状態管理 | `sent.json`（送信済みURLの永続化） |

依存は標準ライブラリ＋`requests` のみ。重いフレームワークは使っていません。

---

## 情報源

`core.py` の `RSS_FEEDS` で自由に差し替え・追加できます。

- TechCrunch AI / VentureBeat AI / MIT Technology Review（海外）
- ITmedia AI＋（日本語）

---

## 構成

```
daily-ai-news/
├── core.py                       # RSS取得・重複除外・Gemini要約・Article変換・送信済み記録
├── main.py                       # 唯一の入口（通知先選択 → 収集 → 要約 → Notifier送信 → 記録）
├── notifiers/
│   ├── __init__.py               # NOTIFY_TARGETS から Notifier を生成
│   ├── slack.py                  # Slack Block Kit 通知
│   ├── discord.py                # Discord Webhook 通知
│   └── line.py                   # LINE push / broadcast 通知
├── tests/                        # 標準 unittest のテスト
├── sent.json                     # 送信済みURLの記録（重複排除の状態。自動更新される）
├── requirements.txt              # 依存ライブラリ
├── README.md
└── .github/workflows/
    └── daily-news-slack.yml      # 毎朝の自動実行設定（cron + timezone）
```

---

## 環境変数

| 変数 | 必須 | 用途 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 必須 | Gemini API キー |
| `NOTIFY_TARGETS` | 任意 | カンマ区切りの通知先。未設定時は `slack` |
| `SLACK_WEBHOOK_URL` | Slack使用時 | Slack Incoming Webhook URL |
| `DISCORD_WEBHOOK_URL` | Discord使用時 | Discord Webhook URL |
| `LINE_CHANNEL_TOKEN` | LINE使用時 | LINE Messaging API のチャネルアクセストークン |
| `LINE_USER_ID` | 任意 | 指定時は push、未指定時は broadcast |

`NOTIFY_TARGETS` の例:

- `slack`
- `slack,discord`
- `slack,discord,line`

未設定または workflow 既定値のままなら Slack のみで動くため、従来の本番挙動は変わりません。

---

## セットアップ

### 1. Gemini API キー

1. [Google AI Studio](https://aistudio.google.com/) にログイン
2. 「Get API key」からキーを発行（クレジットカード不要）
3. 発行された文字列を控える → これが `GEMINI_API_KEY`

### 2. Slack Incoming Webhook URL

1. Slackの [Incoming Webhook ページ](https://api.slack.com/messaging/webhooks) でアプリを作成
2. **Incoming Webhooks** をオンにする
3. **Add New Webhook to Workspace** をクリックし、投稿先チャンネルを選んで許可
4. 発行された Webhook URL をコピー → これが `SLACK_WEBHOOK_URL`

### 3. Discord Webhook URL（任意）

1. Discord の対象チャンネルで **チャンネルを編集 → 連携サービス → ウェブフック** を開く
2. Webhook を作成して URL をコピー → これが `DISCORD_WEBHOOK_URL`
3. `NOTIFY_TARGETS` に `discord` を含める

### 4. LINE Messaging API（任意）

1. LINE Developers で Messaging API チャネルを作成
2. チャネルアクセストークンを発行 → これが `LINE_CHANNEL_TOKEN`
3. 自分だけに送る場合は `LINE_USER_ID` を登録。未登録なら broadcast で送信
4. `NOTIFY_TARGETS` に `line` を含める

### 5. GitHub Secrets に登録

このリポジトリの **Settings → Secrets and variables → Actions → New repository secret** で必要な値を登録します。

必須:

- `GEMINI_API_KEY`
- `SLACK_WEBHOOK_URL`（既定の `NOTIFY_TARGETS: slack` で動かす場合）

Discordを有効化する場合:

- `DISCORD_WEBHOOK_URL`
- workflow の `NOTIFY_TARGETS` を `slack,discord` などに変更

LINEを有効化する場合:

- `LINE_CHANNEL_TOKEN`
- `LINE_USER_ID`（任意）
- workflow の `NOTIFY_TARGETS` を `slack,line` などに変更

**Actions** タブを開き、ワークフローを選んで **Run workflow** で手動実行すると確認できます。

---

## カスタマイズ

- **時刻を変える**: `.github/workflows/daily-news-slack.yml` の `cron: '7 7 * * *'` を編集（`timezone: 'Asia/Tokyo'` を指定済みなので日本時間で書けます）
- **ニュース源を変える**: `core.py` の `RSS_FEEDS` を編集
- **件数を変える**: `core.py` の `TARGET_ARTICLE_COUNT`（初期値5）
- **要約のトーンを変える**: `core.py` の `summarize_with_gemini` 内のプロンプトを調整
- **通知先を変える**: workflow の `NOTIFY_TARGETS` を編集

---

## 注意点（運用上の正直なメモ）

- GitHub Actions の定時実行はベストエフォートで、混雑時は数十分ほど遅れることがあります。
- リポジトリが約60日まったく更新されないと、スケジュール実行が自動停止します。`sent.json` が毎日自動コミットされるため、通常は更新が途切れず、この停止は起きにくい設計になっています。
- Gemini の無料枠は入力が学習に使われる場合があります。気になる場合は有料枠への切り替えを検討してください。
