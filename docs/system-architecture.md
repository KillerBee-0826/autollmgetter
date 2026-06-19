# システム構成図

[システム構成図をdraw.ioで開く](./system-architecture.drawio)

## システム概要

このシステムは、EventBridgeで定期起動されるAWS Lambdaが日本の技術ニュースをRSS/HTMLから収集し、Amazon BedrockのClaudeモデルで日次・週次・月次・四半期レポートを生成してS3へ保存するサーバーレスバッチです。設定とプロンプトはS3の`config/`から読み込み、生成結果は`daily/`、`weekly/`、`monthly/`、`quarterly/`へMarkdownとHTMLで保存します。設定が有効な場合はSESで分析結果へのpresigned URLを通知します。

## コンポーネント一覧

| コンポーネント名 | 種別 | 役割 | 実行環境 | 接続先 | 根拠となるファイル |
| --- | --- | --- | --- | --- | --- |
| 開発者 / 運用者 | 利用者 | ローカル実行、パッケージ作成、Terraform適用、手動Lambda実行 | ローカル端末 | Makefile、Terraform、AWS CLI、Docker、AWS各サービス | `README.md`, `LAMBDA_DEPLOYMENT.md`, `Makefile`, `infra/terraform/` |
| ローカル開発環境 | 開発環境 | Python 3.11でローカル実行、依存関係インストール | ローカル端末 | S3、BedrockなどAWS API | `README.md`, `lambda_handler.py`, `llm_fetcher.py` |
| Docker Layer Build | ビルド環境 | Lambda Layer用依存パッケージをAmazon Linux 2023互換で作成 | ローカルDocker | Lambda Layer zip | `deploy/build_layer.sh`, `deploy/Dockerfile.layer`, `requirements-lambda.txt` |
| Makefile | リリース操作入口 | setup、test、Lambda zip作成、Layer作成、Terraform実行、手動invokeを標準化 | ローカル端末 | Python、Docker、Terraform、AWS CLI | `Makefile` |
| Terraform | IaC | S3、IAM、Secrets Manager、Lambda Layer、Lambda、EventBridge、SES identityを管理 | ローカル端末 + AWS API | AWS各サービス | `infra/terraform/` |
| deploy/deploy.sh | legacy/manual デプロイ手順 | Terraform移行前のLambda Layer公開、Lambda関数作成/更新、環境変数設定 | ローカル端末 + AWS CLI | AWS Lambda | `deploy/deploy.sh` |
| EventBridge Rules | スケジューラ | 日次・週次・月次・四半期の`analysis_type`付き定期起動 | AWS `ap-northeast-1` | AWS Lambda | `README.md`, `LAMBDA_DEPLOYMENT.md`, `lambda_handler.py` |
| AWS Lambda `claude-news-analyzer` | バッチ処理 | 設定読込、ニュース収集、Bedrock分析、S3保存、メール通知制御 | AWS Lambda Python 3.11 | S3、Bedrock、SES、Secrets Manager、CloudWatch Logs、ニュースサイト | `lambda_handler.py`, `llm_fetcher.py`, `deploy/deploy.sh` |
| Lambda Layer | ランタイム依存 | `requests`、`feedparser`、`trafilatura`、`beautifulsoup4`などの依存を提供 | AWS Lambda Layer | AWS Lambda | `deploy/build_layer.sh`, `deploy/Dockerfile.layer`, `requirements-lambda.txt` |
| IAM Role | 認可 | Lambda実行ロールとしてS3、CloudWatch Logs、Bedrock、SES、Secrets Manager権限を付与 | AWS IAM | Lambda、AWS各サービス | `deploy/policies/trust-policy.json`, `deploy/policies/permissions-policy.json` |
| Amazon S3 Bucket | オブジェクトストレージ | 設定/プロンプト読込、分析結果・記事一覧保存、前段レポート入力 | AWS S3 | Lambda、メール受信者のpresigned URLアクセス | `s3_handler.py`, `config/config.json`, `README.md` |
| S3 `config/` | 設定ストア | `config.json`と分析種別ごとのプロンプトを格納 | AWS S3 | Lambda | `lambda_handler.py`, `config/config.json`, `README.md` |
| S3 `daily/` | 出力/入力ストレージ | 日次分析、HTML、記事一覧を保存。週次分析の入力にもなる | AWS S3 | Lambda、メール受信者 | `llm_fetcher.py`, `config/config.json`, `README.md` |
| S3 `weekly/` | 出力/入力ストレージ | 週次分析を保存。月次分析の入力にもなる | AWS S3 | Lambda、メール受信者 | `llm_fetcher.py`, `config/config.json`, `README.md` |
| S3 `monthly/` | 出力/入力ストレージ | 月次分析を保存。四半期分析の入力にもなる | AWS S3 | Lambda、メール受信者 | `llm_fetcher.py`, `config/config.json`, `README.md` |
| S3 `quarterly/` | 出力ストレージ | 四半期分析を保存 | AWS S3 | Lambda、メール受信者 | `llm_fetcher.py`, `config/config.json`, `README.md` |
| S3 `responses/` | 互換用ストレージ | 旧日次レポートを週次分析の入力候補として参照 | AWS S3 | Lambda | `llm_fetcher.py`, `deploy/policies/permissions-policy.json`, `LAMBDA_DEPLOYMENT.md` |
| Amazon Bedrock Runtime | 外部AIサービス | Claudeモデルでニュース分析・集約レポートを生成 | AWS `us-east-1` | Lambda | `bedrock_client.py`, `llm_fetcher.py`, `config/config.json` |
| 技術ニュースサイト | 外部Webサイト | RSSと記事HTML本文の取得元 | インターネット | Lambda | `news_scraper.py`, `config/config.json` |
| Amazon SES | メール送信 | 分析完了通知とpresigned URLを送信 | AWS `ap-northeast-1` | Lambda、メール受信者 | `email_notifier.py`, `config/config.json`, `README.md` |
| AWS Secrets Manager | シークレット管理 | presigned URL署名用IAMユーザーの認証情報を取得 | AWS `ap-northeast-1` | Lambda | `email_notifier.py`, `config/config.json`, `LAMBDA_DEPLOYMENT.md` |
| 署名用IAMユーザー | 認可 | 長期presigned URL生成用のS3 `GetObject`権限 | AWS IAM | S3 | `email_notifier.py`, `LAMBDA_DEPLOYMENT.md` |
| CloudWatch Logs | 監視・ログ | Lambda標準出力ログを保存 | AWS CloudWatch Logs | Lambda | `cloudwatch_logger.py`, `deploy/policies/permissions-policy.json`, `LAMBDA_DEPLOYMENT.md` |
| メール受信者 | 利用者 | SES通知を受信し、presigned URLでS3上のHTML/記事一覧を閲覧 | 外部 | SES、S3 | `email_notifier.py`, `README.md` |

## 通信経路

```text
EventBridge Rules
  → InvokeFunction / Scheduled Event
AWS Lambda
```

```text
AWS Lambda
  → S3 API GetObject
Amazon S3 config/
  → 設定・プロンプト
AWS Lambda
```

```text
AWS Lambda
  → HTTPS GET RSS/HTML
技術ニュースサイト
  → RSS/HTML response
AWS Lambda
```

```text
AWS Lambda
  → Bedrock Runtime InvokeModel / HTTPS
Amazon Bedrock Runtime
  → 生成テキスト
AWS Lambda
```

```text
AWS Lambda
  → S3 API PutObject
Amazon S3 daily/ weekly/ monthly/ quarterly/
```

```text
AWS Lambda
  → S3 API GetObject/ListObjects
Amazon S3 daily/ weekly/ monthly/ responses/
  → 前段レポート
AWS Lambda
```

```text
AWS Lambda
  → GetSecretValue / AWS API
AWS Secrets Manager
  → 署名用認証情報
AWS Lambda
  → generate_presigned_url / S3 API
Amazon S3
```

```text
AWS Lambda
  → SES SendEmail / AWS API
Amazon SES
  → Email
メール受信者
  → HTTPS presigned URL
Amazon S3
```

```text
AWS Lambda
  → stdout / Lambda logging
CloudWatch Logs
```

```text
開発者 / 運用者
  → Docker build
Docker Layer Build
  → lambda-layer.zip
開発者 / 運用者
  → Makefile package-function
  → lambda-function.zip
開発者 / 運用者
  → Terraform plan/apply
AWS Lambda / Lambda Layer
```

```text
Terraform
  → S3 bucket / config objects
  → IAM role / signer user / Secrets Manager secret container
  → Lambda Layer / Lambda function
  → EventBridge rules / targets / permissions
  → optional SES identity
AWS各サービス
```

## 調査根拠

- `README.md`: EventBridge、Lambda、S3、Bedrock、SES、CloudWatch Logs、ニュースサイトの全体構成、日次/週次/月次/四半期処理、S3出力、メール通知を確認。
- `LAMBDA_DEPLOYMENT.md`: S3バケット作成、設定アップロード、IAM、Secrets Manager、SES、Lambda Layer、Lambdaデプロイ、EventBridgeルール、動作確認手順を確認。
- `lambda_handler.py`: `S3_BUCKET_NAME`、S3上の`config/config.json`とプロンプト読込、`analysis_type`の取得、Lambdaエントリーポイントを確認。
- `llm_fetcher.py`: Bedrockクライアント初期化、日次スクレイピング、週次/月次/四半期のS3前段レポート読込、S3保存、SES通知呼び出しを確認。
- `news_scraper.py`: `requests`でRSS/HTMLをHTTPS取得し、本文抽出する処理を確認。
- `bedrock_client.py`: `boto3.client("bedrock-runtime")`と`invoke_model`によるClaude呼び出しを確認。
- `s3_handler.py`: S3の`get_object`、`put_object`、`head_object`、`list_objects_v2`利用を確認。
- `email_notifier.py`: SES v2 `send_email`、Secrets Manager `get_secret_value`、S3 presigned URL生成を確認。
- `config/config.json`: Bedrockモデル/リージョン、S3出力prefix、ニュースサイトURL、SES/Secrets Manager設定キーを確認。
- `deploy/deploy.sh`: Lambda関数名、Layer名、Runtime、Handler、Timeout、Memory、環境変数、Lambda作成/更新手順を確認。
- `deploy/build_layer.sh` と `deploy/Dockerfile.layer`: DockerによるLambda Layerビルドを確認。
- `deploy/policies/*.json`: Lambda実行ロールの信頼ポリシーとS3/CloudWatch Logs/Bedrock/SES/Secrets Manager権限を確認。
- `Makefile`: ローカルセットアップ、テスト、Lambda関数zip作成、Layer作成、Terraform実行、手動invokeの標準入口を確認。
- `infra/terraform/`: S3、IAM、Secrets Manager、Lambda、EventBridge、SES identityのIaC定義を確認。

## 未確認事項

- LambdaのVPC接続、VPC ID、Subnet、Security Group、Availability Zone指定はリポジトリ内で確認できません。
- DNS、CDN、Load Balancer、API Gateway、Webサーバー、APIサーバー、DB、Queue、Cache、認証サービスは確認できません。
- GitHub ActionsなどのCI/CD設定は確認できません。
- S3バケットの暗号化、バージョニング、パブリックアクセスブロック、ライフサイクル設定は確認できません。
- SESのsandbox解除状態、検証済みIdentity、実際に作成済みのEventBridge/Lambda/IAMリソース状態はリポジトリだけでは判断できません。
- Bedrockモデルのアカウント側利用許可状態は確認できません。

## 推測を含む項目

| 項目 | 推測内容 | 理由 | 確度 |
| --- | --- | --- | --- |
| 主AWSリージョン | Lambda、EventBridge、SES、Secrets Manager、CloudWatch Logsは主に`ap-northeast-1`で運用される想定 | `deploy.sh`のデフォルト、`LAMBDA_DEPLOYMENT.md`、`config/config.json`のSES/Secrets Manager設定が一致 | 高 |
| S3バケットリージョン | S3バケットも`ap-northeast-1`想定 | デプロイ手順とpresigned URL用S3リージョンが`ap-northeast-1` | 中 |
| Bedrockリージョン | Bedrock Runtimeのみ`us-east-1`に分離 | `config/config.json`の`bedrock_region`と`bedrock_client.py`のregion指定 | 高 |
| presigned URL利用者 | メール受信者がS3上のHTML/記事一覧をHTTPSで閲覧 | SESメール本文にpresigned URLを含める実装 | 高 |
