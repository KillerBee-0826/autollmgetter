# Bedrock News Analyzer

AWS Lambda 上で日本の技術ニュースを収集し、Amazon Bedrock の Claude モデルで分析して、結果を S3 に保存するサーバーレスアプリケーションです。日次・週次・月次・四半期の分析に対応し、必要に応じて Amazon SES で CloudFront 公開URLを通知します。

## アーキテクチャ

```mermaid
graph TD
    Operator(開発者 / 運用者) --> Terraform(Terraform / Makefile)
    Terraform --> EventBridge(EventBridge Scheduler)
    Terraform --> Lambda(AWS Lambda)
    Terraform --> S3Config(S3 config/)
    Terraform --> S3Policy(S3 bucket policy for CloudFront)
    EventBridge(EventBridge Scheduler) --> Lambda(AWS Lambda)
    Lambda --> S3Config(S3 config/)
    Lambda --> Bedrock(Amazon Bedrock)
    Lambda --> S3Output(S3 daily/ weekly/ monthly/ quarterly/ public/)
    Lambda --> SES(Amazon SES)
    Lambda --> CloudWatch(CloudWatch Logs)
    Lambda --> NewsSites(ニュースサイト)
    SES --> Mail(メール受信者)
    Mail --> CloudFront(CloudFront)
    CloudFront --> S3Public(S3 public/)
```

1. EventBridge が `analysis_type` を渡して Lambda を定期実行します。
2. Lambda が S3 の設定ファイルとプロンプトを読み込みます。
3. 日次分析では RSS と記事本文を取得し、Bedrock で分析します。
4. 週次・月次・四半期分析では S3 の前段レポートを読み込み、Bedrock で集約します。
5. 分析結果と記事一覧を S3 に保存し、設定が有効な場合は SES で CloudFront 公開URLを通知します。

## 主な機能

- 日次・週次・月次・四半期のニュース分析
- RSS と本文抽出による技術ニュース収集
- Amazon Bedrock Claude モデルによる分析レポート生成
- 分析結果のテキスト保存と公開用 HTML 保存
- S3 配置の `config.json` とプロンプトによる設定外部化
- Amazon SES による CloudFront リンク通知
- EventBridge によるスケジュール実行

## 使用技術

- AWS Lambda, Amazon S3, Amazon Bedrock, Amazon SES, Amazon EventBridge, CloudWatch Logs, Secrets Manager
- Python 3.11
- Terraform, Makefile, Docker
- `boto3`, `requests`, `feedparser`, `trafilatura`, `beautifulsoup4`, `chardet`

## ディレクトリ構成

```text
bedrock-news-analyzer/
├── lambda_handler.py       # Lambda エントリーポイント
├── llm_fetcher.py          # 分析フロー制御
├── bedrock_client.py       # Amazon Bedrock クライアント
├── news_scraper.py         # RSS 取得・本文抽出
├── report_saver.py         # レポート保存・公開HTML一覧生成
├── report_loader.py        # 前段レポート読み込み
├── period_calculator.py    # 週次/月次/四半期の期間計算
├── prompt_builder.py       # プロンプトテンプレート置換
├── llm_responder.py        # LLM呼び出しリトライ制御
├── email_dispatcher.py     # メール通知ディスパッチ
├── local_runtime.py        # ローカル直接実行の初期化
├── report_html_renderer.py # 分析結果HTML変換
├── s3_handler.py           # S3 操作
├── email_notifier.py       # SES メール通知
├── cloudwatch_logger.py    # ロガー
├── config/
│   ├── config.json
│   ├── news_analysis_prompt.txt
│   ├── weekly_news_analysis_prompt.txt
│   ├── monthly_news_analysis_prompt.txt
│   └── quarterly_news_analysis_prompt.txt
├── deploy/
│   ├── deploy.sh
│   ├── build_layer.sh
│   └── policies/
├── infra/
│   └── terraform/         # AWS リソース定義
├── docs/
│   └── system-architecture.md
├── Makefile               # ローカル操作・Terraform実行入口
├── LAMBDA_DEPLOYMENT.md    # AWS デプロイ・運用手順
├── requirements.txt
└── requirements-lambda.txt
```

## 最短セットアップ

詳細な初回構築、IAM、CloudFront、SES、EventBridge、ロールバック、トラブルシューティングは [LAMBDA_DEPLOYMENT.md](./LAMBDA_DEPLOYMENT.md) を参照してください。

### 1. ローカル環境

```bash
make setup
source .venv/bin/activate
```

### 2. Terraform 変数

必要に応じて `infra/terraform/terraform.tfvars.example` を `infra/terraform/terraform.tfvars` にコピーし、バケット名、送信元 SES identity、Bedrock モデル、CloudFront distribution ARN/domain name を調整します。`*.tfvars` は Git 管理しません。

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Terraform は `config/config.json` と 4 種類のプロンプトを S3 の `config/` 配下へアップロードします。`bedrock_model`, `bedrock_region`, `email_notification.enabled`, `email_notification.sender`, `public_html.base_url` は Terraform 変数で上書きされます。

### 3. パッケージ作成

```bash
make package-layer
make package-function
```

生成される `lambda-function.zip` と `lambda-layer.zip` は Git 管理しません。

### 4. Terraform 初回構築・更新

```bash
make tf-init
make tf-plan
make tf-apply
```

Terraform は以下を管理します。

- S3 バケット、暗号化、バージョニング、公開アクセスブロック
- 手動作成した CloudFront distribution 向けの `public/` 限定 S3 bucket policy
- S3 `config/config.json` と各プロンプト
- Lambda 実行ロールとインラインポリシー
- Lambda Layer version と Lambda 関数
- EventBridge 4 ルール、ターゲット、Lambda invoke permission
- 旧 presigned URL 互換用の Secrets Manager Secret コンテナ
- 旧 presigned URL 互換用の IAM ユーザーと S3 読み取りポリシー
- 任意の SES identity 作成

旧 presigned URL 互換用リソースは Terraform state との互換のため残していますが、現在のメール通知では使用しません。現行通知に必要なのは、`public_html.base_url` に対応する CloudFront domain name です。

### 5. ローカル実行

AWS 認証情報と S3 バケットを設定したうえで、モックイベントで Lambda 処理を実行できます。

```bash
export S3_BUCKET_NAME="your-s3-bucket-name"
python lambda_handler.py
```

### 6. 手動 invoke

Terraform 適用後、日次処理を手動実行できます。

```bash
make invoke-daily
```

### 7. 手動/legacy デプロイ

`deploy/deploy.sh` は当面残しますが、標準手順は Terraform です。手動で Lambda だけを更新する用途や切り戻し時の参考として利用してください。

## 設定ファイル

S3 に配置する `config/config.json` でモデル、プロンプト、出力先、スクレイピング、メール通知を制御します。

主要項目:

- `bedrock_model`: 使用する Bedrock モデル ID
- `bedrock_region`: Bedrock 呼び出しリージョン
- `prompt_paths`: `daily`, `weekly`, `monthly`, `quarterly` ごとのプロンプトパス
- `output_prefixes`: 分析結果の S3 プレフィックス
- `public_html`: CloudFront 公開用 HTML コピーの有効化、S3 プレフィックス、公開ベースURL
- `news_scraping`: RSS と本文取得の対象・並列数・本文長など
- `email_notification`: SES 通知の有効化、送信元、通知先

## CloudFront 公開

CloudFront distribution は Terraform では作成しません。AWS Console で CloudFront の Free plan を選び、通常の S3 origin + OAC で手動作成します。推奨設定:

- Origin domain: S3 バケットの regional domain
- Origin path: `/public`
- Origin access: OAC、`signing_behavior = always`
- Viewer protocol policy: redirect HTTP to HTTPS
- Allowed methods: GET, HEAD

作成後、distribution ARN と domain name を `infra/terraform/terraform.tfvars` に設定して `make tf-plan` / `make tf-apply` を実行すると、Terraform が `public/*` のみを CloudFront に許可する bucket policy を作成します。

## 出力ファイル

分析結果はMarkdown本文の `.md` と、閲覧用の `.html` を同じプレフィックスに保存します。`public_html.enabled` が `true` の場合、HTML だけを `public/` 配下にも追加保存し、公開HTML一覧の `public/index.html` も再生成します。例:

- 既存の保存先: `s3://claude-news-analyzer/daily/YYYY-MM-DD.html`
- CloudFront 公開用実体: `s3://claude-news-analyzer/public/daily/YYYY-MM-DD.html`
- 公開一覧: `s3://claude-news-analyzer/public/index.html`
- 公開 URL: `https://<cloudfront-domain>/daily/YYYY-MM-DD.html`

CloudFront は S3 website endpoint ではなく通常の S3 origin + OAC を使い、bucket policy は `public/*` の `s3:GetObject` だけを手動作成した CloudFront distribution に許可します。`config/`、Markdown、記事一覧 txt、元の `daily/weekly/monthly/quarterly/` は公開対象外です。既存 HTML を初回公開する場合は `make publish-existing-html` を実行します。

週次・月次・四半期分析の入力には `.md` を優先して使い、移行期間の互換用として過去の `.txt` も参照します。四半期分析は `monthly/YYYY-MM.md` または `monthly/YYYY-MM.txt` を入力にし、`quarterly/FY2026-Q1.md` と `quarterly/FY2026-Q1.html` の形式で保存します。メール通知には対象処理で生成したHTMLレポートと `index.html` の CloudFront リンクだけを載せます。日次の収集記事一覧は `daily/YYYY-MM-DD_articles.txt` として保存しますが、メール通知には含めません。

### メール通知

`email_notification.enabled` を `true` にすると、分析完了後に CloudFront 公開URLを SES で送信します。主な項目は次のとおりです。

- `enabled_analysis_types`: 通知対象の分析種別。例: `["daily", "weekly", "monthly", "quarterly"]`
- `sender`: SES で検証済みの送信元アドレス
- `recipients`: 通知先アドレス
- `fail_on_send_error`: メール送信失敗時に Lambda を失敗扱いにするか

メール通知を有効にする場合は、`public_html.base_url` に CloudFront のベースURLが設定されている必要があります。
