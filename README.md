# 毎朝AIニュースを自動で届けるbot（GitHub Actions × Gemini × Slack）

海外・日本のAIメディアから最新ニュースを集め、Gemini で初心者向けに要約し、**毎朝 自動で Slack に届ける**botです。サーバーもPCの常時起動も不要で、GitHub のサーバー上だけで完結します。**現在も毎日稼働中**。

> RSS収集 → 重複除外 → Gemini要約 → Slack整形 → 送信 → 送信済み記録、までを 1日1回・全自動・無料で回しています。

<img width="300" alt="Slackに届いたニュースまとめ" src="https://github.com/user-attachments/assets/d3b02ab2-10f6-41f1-89ef-d9e0af40603c" />


---

## できること

- 毎朝（日本時間 7時台）に、AI関連の注目ニュース5件を自動でSlackに投稿
- 英語記事も含めてすべて日本語で要約。専門用語には初心者向けのかみくだき解説つき
- 各記事に元記事へのリンク付き
- **同じニュースが翌日以降に重複して届かない**
- 一時的なエラーで「届かない日」が出ないよう、リトライとフォールバックを実装

---

## 設計のポイント（エンジニアリング上の判断）

このbotは「RSSを集めてAIで要約してSlackに流す」だけなら数十行で書けますが、**毎日・自動・無人で安定運用する**ために、次の設計判断を入れています。ここがこのプロジェクトの中身です。

### 1. 使い捨て実行環境でも「記憶」を持たせる（重複排除）
GitHub Actions の実行環境は毎回まっさらに初期化されるため、普通に作ると「昨日何を送ったか」を覚えていられず、同じニュースが繰り返し届きます。
そこで、**実際に送信した記事のURLだけ**を `sent.json` に記録し、ジョブ実行後に Actions 自身がそのファイルをリポジトリへ commit して状態を保持します。翌日はこの記録を参照して既出記事を候補から除外。記録は直近300件で自動トリムし、肥大も防いでいます。
（`load_sent_urls` / `record_sent_urls` / ワークフローの commit ステップ）

### 2. 「届かない日」をなくす障害耐性
外部APIは時々失敗します。素朴に書くと、その一度の失敗で1日分が丸ごと欠落します。
- Gemini呼び出しは、**一時的な失敗（レート制限429・サーバーエラー5xx・タイムアウト・接続断）だけ指数バックオフでリトライ**。恒久的なエラー（不正リクエスト等）は無駄打ちせず即座に判定。
- リトライも全滅した場合は、要約を諦めて**見出し＋リンクの素のリストだけでも必ず投稿**するフォールバックに切り替え。
- 致命的に失敗した場合は、黙って消えずに**Slackへエラー通知**を出す（気づける運用）。
- RSS取得は各フィードを個別に try/except し、1ソースが落ちても全体は止めない。
（`summarize_with_gemini` / `build_fallback_summary` / `send_plain_message_to_slack`）

### 3. 読み手に最適化した出力
- Slack の Block Kit で、見出し・本文・区切り線をカード風に整形。
- 固有名詞（企業名・製品名など）は**アルファベットの原綴りのまま**出力させ、「Anthropic / アンソロピック / アントロピック」のような表記ゆれを排除。
- リンクの自動プレビュー展開（unfurl）を無効化し、見た目をすっきりさせつつ不要な外部アクセスも抑制。

### 4. タイムゾーンを正しく扱うスケジューリング
cron に `timezone: 'Asia/Tokyo'` を明示し、UTC換算ミスによる「意図しない時刻に動く」事故を防止。

### 5. 完全無料で回す構成
Gemini は1日1回しか呼ばないため無料枠の上限にほぼ触れず、GitHub Actions・Slack Webhook も無料枠内。**ランニングコスト0円**で常時稼働します。

---

## 技術スタック

| 領域 | 使用技術 |
| --- | --- |
| 言語 | Python 3.12 |
| 情報収集 | RSS（`urllib` / `xml.etree`）、`requests` |
| 要約 | Google Gemini API（`gemini-2.5-flash`） |
| 通知 | Slack Incoming Webhook（Block Kit） |
| 実行基盤 | GitHub Actions（cron スケジューリング・状態の自動コミット） |
| 状態管理 | `sent.json`（送信済みURLの永続化） |

依存は標準ライブラリ＋`requests` のみ。重いフレームワークは使っていません。

---

## 情報源

`main_slack.py` の `RSS_FEEDS` で自由に差し替え・追加できます。

- TechCrunch AI / VentureBeat AI / MIT Technology Review（海外）
- ITmedia AI＋（日本語）

---

## 構成

```
daily-ai-news/
├── main_slack.py                 # 本体（RSS取得 → 重複除外 → Gemini要約 → Slack送信 → 記録）
├── main.py                       # LINE出力版（別宛先用のバリエーション）
├── sent.json                     # 送信済みURLの記録（重複排除の状態。自動更新される）
├── requirements.txt              # 依存ライブラリ
├── README.md                     # この手順書
└── .github/workflows/
    └── daily-news-slack.yml      # 毎朝の自動実行設定（cron + timezone）
```

---

## セットアップ

無料で揃います。キーを2つ取得して GitHub に登録するだけです。

### 1. Gemini API キー
1. [Google AI Studio](https://aistudio.google.com/) にログイン
2. 「Get API key」からキーを発行（クレジットカード不要）
3. 発行された文字列を控える → これが `GEMINI_API_KEY`

### 2. Slack Incoming Webhook URL
1. Slackの [Incoming Webhook ページ](https://api.slack.com/messaging/webhooks) でアプリを作成（自分のワークスペースを選択）
2. **Incoming Webhooks** をオンにする
3. **Add New Webhook to Workspace** をクリックし、投稿先チャンネルを選んで許可
4. 発行された Webhook URL（`https://hooks.slack.com/services/...`）をコピー → これが `SLACK_WEBHOOK_URL`

### 3. GitHub に登録
1. このリポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下を登録:
   - `GEMINI_API_KEY`
   - `SLACK_WEBHOOK_URL`
2. **Actions** タブを開き、ワークフローを選んで **Run workflow** で手動実行 → Slackに届けば成功

---

## カスタマイズ

- **時刻を変える**: `.github/workflows/daily-news-slack.yml` の `cron: '7 7 * * *'` を編集（`分 時 * * *` の順、`timezone: 'Asia/Tokyo'` を指定済みなので日本時間で書けます）
- **ニュース源を変える**: `main_slack.py` の `RSS_FEEDS` を編集
- **件数を変える**: `TARGET_ARTICLE_COUNT`（初期値5）
- **要約のトーンを変える**: `summarize_with_gemini` 内のプロンプトを調整
- **通知先を変える**: 送信部分を差し替えれば LINE / Discord / メール などにも展開可能

---

## 注意点（運用上の正直なメモ）

- GitHub Actions の定時実行はベストエフォートで、混雑時は数十分ほど遅れることがあります。「正確に7時ちょうど」ではなく「だいたい朝」という設計です（届くことを最優先）。
- リポジトリが約60日まったく更新されないと、スケジュール実行が自動停止します（GitHubの仕様）。`sent.json` が毎日自動コミットされるため、通常は更新が途切れず、この停止は起きにくい設計になっています。
- Gemini の無料枠は入力が学習に使われる場合があります。気になる場合は有料枠への切り替えを検討してください。
