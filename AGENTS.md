# Repository Guidelines

## プロジェクト構成とモジュール

このリポジトリは、Python 3.11 で動作する AWS Lambda サービスです。日本の技術ニュースを収集し、Amazon Bedrock で分析し、結果を S3 に保存します。主要な実装はリポジトリ直下にあります。`lambda_handler.py` は Lambda のエントリーポイント、`llm_fetcher.py` は全体フロー制御、`news_scraper.py` は RSS と本文取得、`bedrock_client.py` は Bedrock 呼び出し、`s3_handler.py` は S3 操作、`cloudwatch_logger.py` は標準出力向けロガー設定を担当します。`email_notifier.py` は SES v2 による CloudFront URL 通知、`report_html_renderer.py` は Markdown 風レポートの HTML 変換を担当します。設定ファイルとプロンプトは `config/`、デプロイスクリプト、Docker Layer 定義、IAM ポリシー例は `deploy/` に配置されています。

## ビルド・テスト・開発コマンド

ローカル環境を作成し、開発用依存関係をインストールします。

```bash
make setup
source .venv/bin/activate
```

ユニットテストを実行します。

```bash
make test
# または
python -m unittest discover -v
```

Lambda 関数 zip と Lambda Layer zip を作成します。

```bash
make package-function
make package-layer
```

モック EventBridge イベントで Lambda 処理をローカル実行します。

```bash
export S3_BUCKET_NAME="your-s3-bucket-name"
python lambda_handler.py
```

Docker を直接使って Lambda Layer を作成する場合は、次のスクリプトを使います。

```bash
./deploy/build_layer.sh
```

Layer と Lambda 関数をデプロイします。

```bash
export LAMBDA_ROLE_ARN="arn:aws:iam::ACCOUNT_ID:role/lambda-claude-news-analyzer"
export S3_BUCKET_NAME="claude-news-analyzer"
export AWS_REGION="ap-northeast-1"
./deploy/deploy.sh
```

## コーディング規約と命名

Python 標準スタイルに従い、インデントは 4 スペースにします。関数・変数は `snake_case`、クラスは `PascalCase`、環境変数や AWS 向け定数は `S3_BUCKET_NAME` のように大文字で記述します。既存コードでは主要な関数シグネチャに型ヒントが使われているため、新規コードでも同じ方針を維持してください。ログは運用時に原因を追える具体的な内容にし、既存の日本語ログ表現と揃えます。

## テスト方針

`test_*.py` に `unittest` ベースの自動テストがあります。変更前後で `python -m unittest discover -v` または `make test` を実行してください。AWS 認証情報と `S3_BUCKET_NAME` を設定したうえで `python lambda_handler.py` を実行すると、S3、Bedrock、スクレイピング処理を含むローカルスモークテストができます。記事の抽出・フィルタ処理を変更する場合は、ライブ通信ではなく小さな fixture ベースの検証を優先します。

## コミットと Pull Request

直近の履歴では `docs:`、`refactor:`、`chore:` などの Conventional Commit 形式が使われています。例: `fix: handle empty RSS feeds`。Pull Request には、運用への影響、変更した AWS リソースや設定キー、検証コマンド、必要な S3 アップロードや環境変数の変更を記載してください。

## セキュリティと設定

認証情報、生成済み zip、ローカル AWS プロファイルはコミットしないでください。`config/config.json` と `config/news_analysis_prompt.txt` は S3 配置用テンプレートとして扱い、本番実行時は S3 の `config/` 配下から読み込まれます。IAM ポリシーを変更する場合は最小権限を維持し、Bedrock、S3、Lambda、EventBridge、CloudWatch の追加権限を PR に明記してください。
