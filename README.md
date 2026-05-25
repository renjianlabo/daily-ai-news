# 毎朝AIニュースを届ける（GitHub Actions + Gemini）

毎朝7時（日本時間）に、最新のAI関連ニュースを海外・日本のメディアから集めて Gemini で要約し、**LINE または Slack** に送る仕組みです。初心者にもわかりやすいよう、専門用語に解説をつけた新聞記事風の要約を5件お届けします。PC を起動しておく必要はありません（GitHub のサーバー上で動きます）。

**LINE版とSlack版の両方が入っています。** 使う方を選んでください（後述）。読みやすさ重視ならSlack版がおすすめです（太字の見出し・記事ごとの区切り線でカード風に整います）。

## 情報源

海外（英語）と日本語のAIメディアを混ぜています（`main.py` の `RSS_FEEDS` で変更可）。
- TechCrunch AI / VentureBeat AI / MIT Technology Review（海外）
- ITmedia AI＋（日本語）

英語記事も含めて、要約はすべて日本語で届きます。

## 構成

```
daily-news-line/
├── main.py                       # LINE版の本体（RSS取得 → Gemini要約 → LINE送信）
├── main_slack.py                 # Slack版の本体（RSS取得 → Gemini要約 → Slack送信）
├── requirements.txt              # 依存ライブラリ
├── README.md                     # この手順書
└── .github/workflows/
    ├── daily-news.yml            # LINE版の自動実行設定
    └── daily-news-slack.yml      # Slack版の自動実行設定
```

⚠️ **重要**: 両方のワークフローを残すと、LINEとSlackの両方に毎朝届きます。片方だけ使うなら、不要な方のワークフローファイル（`.github/workflows/` 内の `.yml`）を削除するか、GitHubのActionsタブで該当ワークフローを「Disable」してください。

## 必要なもの

無料で揃います。3つのキーを取得して GitHub に登録するのが準備のメインです。

### 1. Gemini API キー

1. [Google AI Studio](https://aistudio.google.com/) にログイン
2. 「Get API key」からキーを発行（クレジットカード不要）
3. 発行された文字列を控える → これが `GEMINI_API_KEY`

無料枠は 2026年時点で Gemini 2.5 Flash が1日あたり250リクエスト程度。**この仕組みは1日1回しか呼ばない**ので、上限の1%も使いません。余裕で無料に収まります。

### 2. 送信先の設定（SlackかLINEのどちらか）

#### ▶ Slack版を使う場合（推奨・最短）

1. Slackの [Incoming Webhook ページ](https://api.slack.com/messaging/webhooks) を開き、「Create your Slack app」からアプリを作成（自分のワークスペースを選択）
2. 左メニューの **Incoming Webhooks** をオンにする
3. **Add New Webhook to Workspace** をクリックし、投稿先のチャンネルを選んで許可
4. 発行された **Webhook URL**（`https://hooks.slack.com/services/...`）をコピー → これが `SLACK_WEBHOOK_URL`

LINEと違い、友だち追加やユーザーID確認は不要です。URLを1つコピーするだけで完了します。

#### ▶ LINE版を使う場合

1. [LINE Developers](https://developers.line.biz/) にログイン
2. 新規プロバイダー → 新規チャネル（**Messaging API**）を作成
3. 作成したチャネルの「Messaging API設定」タブで **チャネルアクセストークン（長期）** を発行 → これが `LINE_CHANNEL_TOKEN`
4. 同じチャネルの「チャネル基本設定」タブ最下部の **あなたのユーザーID** を控える → これが `LINE_USER_ID`
5. **重要**: スマホの LINE でこのチャネル（公式アカウント）を友だち追加しておく。追加しないとメッセージが届きません。

### 3. GitHub に登録

1. このフォルダを自分の GitHub リポジトリにアップロード（git push、またはWeb上でアップロード）
2. 使わない方のワークフローを削除/Disableする（`daily-news.yml`＝LINE、`daily-news-slack.yml`＝Slack）
3. リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で、使う方に応じて登録:
   - 共通: `GEMINI_API_KEY`
   - Slack版: `SLACK_WEBHOOK_URL`
   - LINE版: `LINE_CHANNEL_TOKEN` と `LINE_USER_ID`

## 動作テスト

スケジュールを待たずに今すぐ試せます。

1. リポジトリの **Actions** タブを開く
2. 使う方のワークフロー（Slackなら「Daily AI News to Slack」、LINEなら「Daily News to LINE」）を選択 → **Run workflow** をクリック
3. 数十秒待って、SlackまたはLINEにニュースまとめが届けば成功

## カスタマイズ

- **時刻を変える**: 使う方の `.yml`（`daily-news.yml` または `daily-news-slack.yml`）の `cron: '0 7 * * *'` を編集（`分 時 * * *` の順、日本時間）。例: 朝6時半なら `'30 6 * * *'`
- **ニュース源を変える**: `main.py` / `main_slack.py` の `RSS_FEEDS` を編集。好きなAI系RSSのURLを追加・削除できます
- **件数を変える**: `TARGET_ARTICLE_COUNT`（初期値5）を変更
- **要約のトーンや丁寧さを変える**: `summarize_with_gemini` 内のプロンプトを書き換える（「中学生でも理解できる」の部分などを調整）

## 注意点

- GitHub Actions の定時実行は、混雑時に数分〜30分ほど遅れることがあります（仕様）。「正確に7時ちょうど」ではなく「だいたい朝」くらいの感覚で。
- リポジトリが60日間まったく更新されないと、スケジュール実行が自動で止まります。たまに何かコミットするか、Actionsタブから再有効化すればOK。
- Gemini の無料枠はプロンプトが学習に使われる場合があります。気になる場合は有料枠（それでも安価）への切り替えを検討してください。
