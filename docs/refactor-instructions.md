# Refactor Instructions — bedrock-news-analyzer

> **この文書について**: この文書は、実装担当モデル (Codex, Opus 等) がリファクタリングを安全に完遂するための指示書です。
> 人間は `/goal refactor-instructions.md に書かれたことを完遂しろ` の形で渡してください。

---

## Objective

既存の動作仕様を一切壊さずに、以下の目標を達成する:

1. `llm_fetcher.py`（1064行）の責務を分割し、各モジュールが単一責務になるようにする
2. コードとドキュメントの乖離を解消する
3. テストが存在しないモジュール (`news_scraper.py`, `bedrock_client.py`, `cloudwatch_logger.py`) にユニットテストを追加する
4. ローカルモードとLambdaモードの初期化パターンを整理する
5. 死コード・到達不能コードを安全に除去する

**禁止事項**: 公開API (Lambda レスポンス形式)、S3 パス構造、EventBridge イベント形式、設定ファイルのスキーマ、メール通知のフォーマットを変更してはならない。

---

## Project Understanding

### このプロジェクトは何をするものか

AWS Lambda 上で動作する Python 3.11 のサーバーレスアプリケーション。
日本の技術ニュースを RSS 経由で収集し、Amazon Bedrock (Claude) で分析し、結果を S3 に保存して SES でメール通知する。
日次・週次・月次・四半期の4種類のレポートを生成する。

### 主要なユーザー体験/ワークフロー

1. EventBridge が `analysis_type` を含むイベントで Lambda をトリガー
2. Lambda が S3 から `config/config.json` と対応するプロンプトテンプレートを読み込み
3. **日次**: RSS からニュース収集 → 本文スクレイピング → Bedrock で分析 → `.md` + `.html` で S3 保存 → `public/` にHTMLコピー → SES 通知
4. **週次/月次/四半期**: S3 から前段レポートを読み込み → Bedrock で集約分析 → 同様に保存・通知
5. CloudFront 経由で `public/` のHTMLが閲覧可能

### 主要エントリーポイント

| ファイル | 用途 | 呼び出し方 |
|----------|------|-----------|
| `lambda_handler.py` → `lambda_handler()` | Lambda 本番用 | EventBridge / `make invoke-daily` |
| `lambda_handler.py` → `local_test()` | ローカルテスト (Lambda 経由) | `PYTHONPATH=src python -m bedrock_news_analyzer.lambda_handler` |
| `llm_fetcher.py` → `main()` | ローカルテスト (直接実行) | `PYTHONPATH=src python -m bedrock_news_analyzer.llm_fetcher` |

### 主要モジュールと責務

| ファイル | 行数 | 責務 |
|----------|------|------|
| `lambda_handler.py` | 175 | Lambda エントリーポイント、イベント解析、S3 からの設定/プロンプト読み込み |
| `llm_fetcher.py` | **1064** | **全体フロー制御** + ニュース分析指示 + レポート保存 + 公開HTML管理 + 定期レポート集約 + メール通知ディスパッチ + ローカルモード初期化 + HTML index 生成 + 日付/期間計算 |
| `news_scraper.py` | 765 | RSS 取得、本文スクレイピング (trafilatura/BS4/chardet)、並列処理、日付フィルタリング |
| `bedrock_client.py` | 185 | Bedrock Claude API 呼び出し、リトライ、トークン使用量追跡 |
| `s3_handler.py` | 227 | S3 CRUD (JSON/text/markdown/HTML)、オブジェクト存在確認、リスト |
| `cloudwatch_logger.py` | 83 | Python logging セットアップ (stdout 出力) |
| `email_notifier.py` | 179 | SES v2 メール通知、CloudFront URL 生成 |
| `report_html_renderer.py` | 419 | Markdown → HTML 変換 (純粋関数、外部依存なし) |

### データフロー

```
EventBridge → lambda_handler.py
  → S3 config/config.json 読み込み
  → S3 config/{analysis_type}_prompt.txt 読み込み
  → LLMFetcher.__init__(config, prompt_template, s3_handler, logger)
  → LLMFetcher.run(analysis_type)
    ├─ daily → NewsScraper → 記事収集 → Bedrock → S3 保存 → 公開HTML → Email
    ├─ weekly → S3 日次レポート読み込み → Bedrock → S3 保存 → 公開HTML → Email
    ├─ monthly → S3 週次レポート読み込み → Bedrock → S3 保存 → 公開HTML → Email
    └─ quarterly → S3 月次レポート読み込み → Bedrock → S3 保存 → 公開HTML → Email
```

### 外部依存

**AWS サービス**: S3, Bedrock Runtime, SES v2, CloudWatch Logs, EventBridge
**Python パッケージ** (requirements.txt): boto3, feedparser, beautifulsoup4, lxml, requests, pytz, python-dateutil, trafilatura, chardet, html5lib, python-dotenv
**Lambda Layer** (requirements-lambda.txt): 上記から boto3, python-dotenv を除いたもの

### 検証コマンド

```bash
# ユニットテスト
python -m unittest discover -v

# ローカル実行 (AWS 認証情報 + S3_BUCKET_NAME 必要)
export S3_BUCKET_NAME="your-bucket"
PYTHONPATH=src python -m bedrock_news_analyzer.lambda_handler

# Lambda パッケージ
make package-function
make package-layer

# Terraform
make tf-plan
```

---

## Behaviors To Preserve

以下は**絶対に壊してはいけない**既存挙動である:

1. **Lambda レスポンス形式**: `{'statusCode': int, 'body': json_string}` — `body` 内の `success`, `error`, `message` キー
2. **S3 パス構造**: `daily/YYYY-MM-DD.md`, `daily/YYYY-MM-DD.html`, `weekly/start_end.md`, `monthly/YYYY-MM.md`, `quarterly/FY20XX-QN.md` および対応する `.html`
3. **公開HTML コピー**: `public/` 配下に HTML をコピーし、`public/index.html` を再生成する機能
4. **EventBridge イベント解析**: `event.analysis_type` → `event.detail.analysis_type` → デフォルト `"daily"` のフォールバック
5. **config.json のスキーマ**: 既存のキー名と構造 (`llm_provider`, `bedrock_model`, `prompt_paths`, `output_prefixes`, `public_html`, `email_notification`, `news_scraping`)
6. **4月始まりの会計年度**: `_get_previous_quarter_range()` の FY20XX-QN 形式
7. **レポート読み込みの互換性**: `.md` 優先 → `.txt` フォールバック → 旧 `responses/` フォールバック
8. **メール通知**: CloudFront リンクのみを含む SES v2 メール
9. **ローカル実行モード**: `PYTHONPATH=src python -m bedrock_news_analyzer.llm_fetcher` での `__init_local__` 経由のスタンドアロン実行
10. **遅延インポート**: `news_scraper` (L292) と `email_notifier` (L983) の遅延インポートパターン（Lambda コールドスタート最適化）
11. **記事一覧保存**: `daily/YYYY-MM-DD_articles.txt` の保存
12. **既存質問処理**: `config.question` が設定されている場合の追加 LLM 呼び出し (L862-866)

---

## Non-Negotiables

- **既存テストを壊さない**: `python -m unittest discover -v` が全件パスし続けること
- **モジュールのインポートパス不変**: 他モジュールからの `from llm_fetcher import LLMFetcher` が引き続き動作すること
- **deploy/deploy.sh の zip 対象ファイルリスト**: 新規ファイルを追加した場合は `deploy/deploy.sh`, `Makefile`, `infra/terraform/main.tf` のファイルリストも更新すること
- **config.json のバックワード互換**: 既存の S3 上の config.json がそのまま動作すること
- **Conventional Commits**: `refactor:`, `test:`, `docs:` プレフィックスを使用

---

## Stop And Ask Conditions

以下の状況に遭遇した場合、**実装を止めて人間に質問**すること:

1. `__init_local__` メソッド内で `os.chdir()` を呼んでいるが、これを削除してよいか不明な場合
2. `config.question` による追加 LLM 呼び出し機能が現在も使われているか不明な場合
3. S3 パス構造の変更が必要に思える場合
4. `_get_previous_quarter_range()` の4月始まり会計年度ロジックに修正が必要に見える場合
5. `deploy/policies/permissions-policy.json` のハードコードされたアカウントID `235217802903` を変更すべきか不明な場合
6. `report_html_renderer.py` の HTML 変換ロジックに機能変更が必要に思える場合
7. プロンプトテンプレートの内容を変更する必要がある場合
8. テストの期待値が既存実装と矛盾する場合

---

## Baseline Commands

リファクタリング開始前に、必ず以下を実行して結果を記録せよ:

```bash
# 1. git 状態確認
git status
git log --oneline -5

# 2. 既存テスト実行 (ベースライン)
python -m unittest discover -v 2>&1 | tee /tmp/baseline-test-result.txt

# 3. パッケージ作成の確認
make package-function
ls -lh lambda-function.zip

# 4. ファイル行数の記録
wc -l lambda_handler.py llm_fetcher.py news_scraper.py bedrock_client.py s3_handler.py cloudwatch_logger.py email_notifier.py report_html_renderer.py
```

---

## Debt Map

### DEBT-1: `llm_fetcher.py` が God Class (1064行)

**根拠**: `llm_fetcher.py` — 1064行、13以上のパブリック/プライベートメソッド
**なぜ負債か**: 単一ファイルに以下の責務が混在:
  - ニュース分析フロー制御 (`run_daily`, `run_weekly`, `run_monthly`, `run_quarterly`)
  - レポート保存 (`save_response`, `save_periodic_response`)
  - 公開HTML管理 (`_save_public_html_copy`, `_refresh_public_html_index`, `_render_public_html_index`)
  - 日付/期間計算 (`_get_previous_week_range`, `_get_previous_month_range`, `_get_previous_quarter_range`)
  - 前段レポート読み込み (`_load_daily_analysis`, `_load_weekly_analyses_for_month`, `_load_monthly_analyses_for_quarter`)
  - プロンプト生成 (`_create_news_analysis_prompt`, `_create_periodic_analysis_prompt`)
  - メール通知ディスパッチ (`_send_email_notification`)
  - ローカルモード初期化 (`__init_local__`, `_load_config`, `_load_prompt_template`, `_setup_logging`)
  - LLM 呼び出しリトライ (`fetch_response`)
  - HTML インデックスのフルHTML生成（60行のインラインCSS）

**影響範囲**: すべてのテスト、すべてのインポートパス
**変更リスク**: 中 — モジュール分割は慎重に行えば安全だが、インポートパスの互換性に注意
**改善案**: Phase 3-5 で段階的に分割 (後述)
**検証方法**: 全テスト通過 + `from llm_fetcher import LLMFetcher` が動作すること
**実装可否**: ✅ 実装してよい (段階的に)

---

### DEBT-2: `__init_local__` のダブル初期化パターン

**根拠**: `llm_fetcher.py` L82-138 — `__init__` と `__init_local__` の2つの初期化メソッド、`main()` で `object.__new__(LLMFetcher)` + `__init_local__()` という異例のパターン
**なぜ負債か**: `__init_local__` は通常の `__init__` をバイパスしており、Bedrock クライアント初期化コードが L57-74 と L107-124 で完全に重複。`os.chdir()` の副作用もある。
**影響範囲**: ローカル実行モード (`PYTHONPATH=src python -m bedrock_news_analyzer.llm_fetcher`)
**変更リスク**: 中 — ローカルモードの動作確認が必要
**改善案**: `__init__` にローカル/Lambda の分岐を統合するか、ファクトリメソッドに変更
**検証方法**: `PYTHONPATH=src python -m bedrock_news_analyzer.llm_fetcher` がローカルで動作すること
**実装可否**: ✅ 実装してよい (ただし `os.chdir()` の削除は Stop And Ask)

---

### DEBT-3: ドキュメントとコードの乖離

**根拠**:
- `AGENTS.md` (L10): 「`cloudwatch_logger.py` は AWS 操作とログ出力を担当」 → 実際は `setup_cloudwatch_logger()` 関数を提供するだけの83行のロガーモジュール
- `AGENTS.md` の「テスト方針」セクション: 「専用の自動テストスイートはありません」 → 実際には6つのテストファイルが存在
- `AGENTS.md` の「ビルド・テスト・開発コマンド」: `pip install -r requirements.txt` / `PYTHONPATH=src python -m bedrock_news_analyzer.lambda_handler` → 実際は `make setup` / `make test`
- `README.md` の一部の構成例で `rss_feeds` を参照しているが、実際の config.json では `news_scraping.sites` が使われている
- `docs/system-architecture.md`: CloudFront/public_html 周りの記述が一部欠落

**影響範囲**: 開発者の理解、新規貢献者のオンボーディング
**変更リスク**: 低 — ドキュメントのみの変更
**改善案**: Phase 2 でドキュメントを現状のコードに合わせて更新
**検証方法**: ドキュメント内のコマンドが実際に動作すること
**実装可否**: ✅ 実装してよい

---

### DEBT-4: テスト不足

**根拠**:
- `news_scraper.py` (765行): **テストなし** — RSS パース、本文抽出、並列処理、日付フィルタリングのいずれもテストされていない
- `bedrock_client.py` (185行): **テストなし** — API 呼び出し、リトライロジック、エラーハンドリングがテストされていない
- `cloudwatch_logger.py` (83行): **テストなし**
- `llm_fetcher.py`: `run_daily`, `run_weekly`, `run_monthly` のテストなし (`run_quarterly` のみテスト済み)
- `s3_handler.py`: `load_json`, `load_text`, `object_exists`, `list_objects` のテストなし (save 系のみテスト済み)
- `email_notifier.py`: SES エラー時のテスト不足

**影響範囲**: リファクタリングの安全性に直結
**変更リスク**: 低 — テスト追加のみ
**改善案**: Phase 1 で安全網として最低限のテストを追加
**検証方法**: `python -m unittest discover -v` で新テストが通ること
**実装可否**: ✅ 実装してよい

---

### DEBT-5: Bedrock クライアント初期化の重複

**根拠**: `llm_fetcher.py` L54-74 と L104-124 — 全く同じ Bedrock クライアント初期化コードが2箇所に存在
**なぜ負債か**: 一方を更新して他方を忘れるリスク
**影響範囲**: LLMFetcher の初期化
**変更リスク**: 低 — ヘルパーメソッドへの抽出
**改善案**: `_init_bedrock_client(self)` プライベートメソッドに統合
**検証方法**: 既存テスト通過
**実装可否**: ✅ 実装してよい

---

### DEBT-6: `llm_fetcher.py` 内のインライン HTML テンプレート

**根拠**: `llm_fetcher.py` L454-517 — `_render_public_html_index()` 内に60行のインライン CSS + HTML テンプレート
**なぜ負債か**: HTML生成の責務が `report_html_renderer.py` と `llm_fetcher.py` に分散。レンダリングロジックの一貫性が損なわれている。
**影響範囲**: 公開 HTML インデックスの見た目
**変更リスク**: 低 — 出力 HTML の構造が変わらなければ安全
**改善案**: Phase 5 で `report_saver.py` に移動 (HTML生成ヘルパーとして)
**検証方法**: 生成される `public/index.html` の内容が変わらないこと
**実装可否**: ✅ 実装してよい

---

### DEBT-7: `save_response` / `save_periodic_response` の S3/ローカル分岐重複

**根拠**: `llm_fetcher.py` L719-841 — 2つの保存メソッドが「S3の場合」「ローカルの場合」を同じパターンで分岐。HTML 生成 + 公開コピーのロジックも両方に含まれる。
**なぜ負債か**: 同じ保存パターンが2メソッドに散在し、変更時に漏れやすい
**影響範囲**: レポート保存機能
**変更リスク**: 中 — 保存先パスの互換性に注意
**改善案**: Phase 4 で共通の保存ヘルパーに統合
**検証方法**: 日次・定期レポートの保存パスが変わらないこと
**実装可否**: ✅ 実装してよい

---

### DEBT-8: `_save_formatted_articles` 内の S3/ローカル分岐

**根拠**: `llm_fetcher.py` L312-347
**なぜ負債か**: DEBT-7 と同パターンの S3/ローカル分岐
**影響範囲**: 記事一覧保存
**変更リスク**: 低
**改善案**: DEBT-7 と同時に共通化
**検証方法**: `daily/YYYY-MM-DD_articles.txt` の保存が変わらないこと
**実装可否**: ✅ 実装してよい

---

### DEBT-9: `deploy/deploy.sh` と `Makefile` のファイルリスト不一致リスク

**根拠**:
- `deploy/deploy.sh`: `zip -r lambda-function.zip` で8ファイルをハードコード
- `Makefile` (`FUNCTION_SOURCES`): 8ファイルを変数で定義
- `infra/terraform/main.tf`: Lambda function の `filename` で zip を参照

**なぜ負債か**: モジュール分割でファイルを追加した場合、3箇所すべてを更新する必要がある
**影響範囲**: デプロイの正常性
**変更リスク**: 高 — 漏れるとデプロイ後に ImportError
**改善案**: Phase 3 以降でファイルを追加した場合は必ず3箇所を更新
**検証方法**: `make package-function && unzip -l lambda-function.zip` で全ファイル含まれていること
**実装可否**: ✅ 実装してよい (ファイル追加時に忘れないこと)

---

### DEBT-10: エラーハンドリングの不統一

**根拠**:
- `llm_fetcher.py` L270: 広い `Exception` キャッチでリトライ
- `llm_fetcher.py` L345-347: `Exception` キャッチで re-raise
- `llm_fetcher.py` L1033: トップレベルで `Exception` キャッチして `False` 返却
- `lambda_handler.py` L119: トップレベルで `Exception` キャッチして 500 返却
- `_create_news_analysis_prompt` (L700-701): エラー時に `print()` + `sys.exit(1)` — Lambda 環境では不適切

**なぜ負債か**: `sys.exit(1)` は Lambda 環境ではプロセスを kill するため、正しいエラーレスポンスを返せない
**影響範囲**: Lambda のエラーレスポンス
**変更リスク**: 低 — `sys.exit(1)` を例外送出に置き換えるだけ
**改善案**: Phase 3 で `sys.exit(1)` を適切な例外に変更
**検証方法**: Lambda エラー時に 500 レスポンスが返ること
**実装可否**: ✅ 実装してよい

---

## Implementation Phases

### Phase 0: ベースライン記録 (変更なし)

1. `git status` で未コミット変更がないことを確認
2. Baseline Commands (前述) を実行し、結果を記録
3. 既存テストが全件パスすることを確認
4. `wc -l` でファイル行数を記録

---

### Phase 1: 安全網の構築 — テスト追加

> **目的**: リファクタリング前に壊れやすい箇所にテストを張る

#### 1-1. `test_bedrock_client.py` 新規作成

- `BedrockClient.__init__` のパラメータ受け渡しテスト (boto3 をモック)
- `generate_content` の正常系テスト (boto3.client.invoke_model をモック)
- `ClientError (ThrottlingException)` 時のリトライテスト
- `get_usage_stats` のテスト
- max_tokens 到達時の warning ログテスト

#### 1-2. `test_news_scraper.py` 新規作成

- `NewsScraper.__init__` の config 読み込みテスト
- `_parse_rss_date` の各フォーマットテスト (RFC2822, ISO8601, 日本語)
- `_is_yesterday_article` のタイムゾーン考慮テスト
- `_validate_content` のテスト (最小長、文字化け、ボイラープレート)
- `format_articles_for_llm` のフォーマットテスト
- `_fetch_from_rss` のモックテスト (feedparser をモック)
- `_decode_response` のエンコーディング検出テスト

**注意**: ネットワーク呼び出しは全てモック。fixture ベース。

#### 1-3. `test_cloudwatch_logger.py` 新規作成

- `setup_cloudwatch_logger` がロガーを返すこと
- `setup_minimal_logger` がロガーを返すこと
- `get_logger` が同じロガーを返すこと
- ハンドラの重複追加がないこと

#### 1-4. 既存テストの補強

- `test_s3_handler.py`: `load_json`, `load_text`, `object_exists`, `list_objects` のテスト追加
- `test_lambda_handler.py`: `daily`, `weekly`, `monthly` の正常系テスト追加

#### 検証

```bash
python -m unittest discover -v
```

全テスト (既存 + 新規) がパスすること。

---

### Phase 2: ドキュメント更新

> **目的**: ドキュメントを現在のコードに合わせる

#### 2-1. `AGENTS.md` の更新

- 「テスト方針」セクション: テストファイルの存在と `python -m unittest discover -v` コマンドを記載
- 「ビルド・テスト・開発コマンド」: `make setup`, `make test`, `make package-function`, `make package-layer` を記載
- モジュール説明: `cloudwatch_logger.py` の説明を実態 (ロガーファクトリ関数) に合わせる
- `email_notifier.py`, `report_html_renderer.py` の説明を追加

#### 2-2. `docs/system-architecture.md` の更新

- コンポーネント詳細が現在のメソッドシグネチャと一致するよう更新
- 特に `LLMFetcher.__init__` のパラメータが `(config, prompt_template, s3_handler, logger)` であることを明記

#### 検証

ドキュメント内のコマンドを手動で確認。コード変更なし。

---

### Phase 3: 安全な整理 — 死コード除去と小修正

> **目的**: 明らかに安全な整理を行う

#### 3-1. `sys.exit(1)` の除去

`llm_fetcher.py` 内の以下の `sys.exit(1)` を適切な例外に置き換え:
- L156 (`_load_config`): `SystemExit` → そのまま `sys.exit` を維持 (ローカルモード専用メソッド)
- L160 (`_load_config`): 同上
- L182 (`_load_prompt_template`): 同上
- L191 (`_load_prompt_template`): 同上
- L195 (`_load_prompt_template`): 同上
- L199 (`_load_prompt_template`): 同上
- **L701** (`_create_news_analysis_prompt`): `sys.exit(1)` → `raise ValueError(...)` — **これは Lambda 経由でも呼ばれるため修正必須**

#### 3-2. Bedrock 初期化コードの重複除去

`__init__` と `__init_local__` の共通部分を `_init_bedrock_client(self)` プライベートメソッドに抽出。

```python
def _init_bedrock_client(self) -> None:
    provider = self.config.get("llm_provider", "bedrock")
    self.logger.info(f"LLMプロバイダー: {provider}")
    if provider == "bedrock":
        model_id = self.config.get("bedrock_model", "us.anthropic.claude-sonnet-4-5-v2:0")
        # ... (既存コードをそのまま移動)
    else:
        raise ValueError(f"未サポートのLLMプロバイダー: {provider}")
```

#### 3-3. 不要な `print()` 文の整理

`llm_fetcher.py` 内で `self.logger` と `print()` が並列使用されている箇所:
- ローカルモード専用 (`__init_local__` 内) のものは維持
- Lambda 経由で到達する L700 の `print()` は削除

#### 検証

```bash
python -m unittest discover -v
PYTHONPATH=src python -m bedrock_news_analyzer.lambda_handler  # ローカル実行 (S3_BUCKET_NAME 要設定)
```

---

### Phase 4: 責務分離 — レポート保存の切り出し

> **目的**: `llm_fetcher.py` からレポート保存ロジックを分離

#### 4-1. `report_saver.py` 新規作成

以下のメソッドを `llm_fetcher.py` から `ReportSaver` クラスに移動:
- `save_response` → `save_daily_report`
- `save_periodic_response` → `save_periodic_report`
- `_save_formatted_articles`
- `_get_output_prefix`
- `_save_public_html_copy`
- `_refresh_public_html_index`
- `_render_public_html_index` (HTML テンプレート含む)
- `_get_public_html_prefix`

```python
# report_saver.py
class ReportSaver:
    def __init__(self, config: dict, s3_handler, logger):
        self.config = config
        self.s3_handler = s3_handler
        self.logger = logger
```

#### 4-2. `llm_fetcher.py` の更新

- `ReportSaver` をインポートし、`__init__` で初期化
- 各 `run_*` メソッド内で `self.report_saver.save_daily_report(...)` 等を呼ぶように変更
- `LLMFetcher` から移動したメソッドを削除

#### 4-3. デプロイファイルの更新

- `deploy/deploy.sh`: zip 対象に `report_saver.py` を追加
- `Makefile` の `FUNCTION_SOURCES`: `report_saver.py` を追加

#### 4-4. テスト

- `test_report_saver.py` 新規作成: 各保存メソッドのテスト
- 既存テストが引き続きパスすること

#### 検証

```bash
python -m unittest discover -v
make package-function && unzip -l lambda-function.zip  # report_saver.py が含まれていること
```

---

### Phase 5: 責務分離 — 日付/期間計算の切り出し

> **目的**: `llm_fetcher.py` から日付計算ロジックを分離

#### 5-1. `period_calculator.py` 新規作成

以下のメソッドを移動 (関数モジュールまたはクラス):
- `_get_now`
- `_get_previous_week_range`
- `_get_previous_month_range`
- `_get_previous_quarter_range`

```python
# period_calculator.py
import pytz
from datetime import datetime, timedelta

def get_now(config: dict) -> datetime:
    timezone_name = config.get("news_scraping", {}).get("timezone", "Asia/Tokyo")
    tz = pytz.timezone(timezone_name)
    return datetime.now(tz)
```

#### 5-2. デプロイファイルの更新

`deploy/deploy.sh` と `Makefile` に `period_calculator.py` を追加。

#### 5-3. テスト

- `test_period_calculator.py` 新規作成: 各期間計算のテスト (特に4月始まり会計年度)
- 既存テストが引き続きパスすること

#### 検証

```bash
python -m unittest discover -v
```

---

### Phase 6: 責務分離 — 前段レポート読み込みの切り出し

> **目的**: `llm_fetcher.py` から前段レポート読み込みロジックを分離

#### 6-1. `report_loader.py` 新規作成

以下のメソッドを移動:
- `_load_text_if_exists`
- `_load_daily_analysis`
- `_load_weekly_analyses_for_month`
- `_load_monthly_analyses_for_quarter`

#### 6-2. デプロイファイルの更新

`deploy/deploy.sh` と `Makefile` に `report_loader.py` を追加。

#### 6-3. テスト

- `test_report_loader.py` 新規作成: S3 モックを使った読み込みテスト
- `.md` 優先 → `.txt` フォールバックの互換性テスト

#### 検証

```bash
python -m unittest discover -v
```

---

### Phase 7: 最終検証と整理

#### 7-1. ファイル行数の確認

```bash
wc -l lambda_handler.py llm_fetcher.py news_scraper.py bedrock_client.py s3_handler.py cloudwatch_logger.py email_notifier.py report_html_renderer.py report_saver.py period_calculator.py report_loader.py
```

`llm_fetcher.py` が 400 行以下になっていることを確認。

#### 7-2. 全テスト実行

```bash
python -m unittest discover -v 2>&1 | tee /tmp/final-test-result.txt
```

#### 7-3. パッケージ確認

```bash
make package-function
unzip -l lambda-function.zip
```

新規ファイルが全て含まれていること。

#### 7-4. `__init_local__` の動作確認

```bash
PYTHONPATH=src python -m bedrock_news_analyzer.llm_fetcher  # ローカルモードのスモークテスト (S3 接続が必要)
```

---

## Verification Requirements

各フェーズ完了後に必ず実行:

1. `python -m unittest discover -v` — 全テストパス
2. `git diff --stat` — 変更ファイル数の確認
3. Phase 4-6 では `make package-function && unzip -l lambda-function.zip` — デプロイパッケージの確認

---

## Reporting Format

各フェーズ完了後、以下の形式で報告すること:

```
## Phase N 完了報告

### 実行したこと
- ...

### 変更ファイル
- `file.py`: 変更内容の要約

### テスト結果
- 実行コマンド: `python -m unittest discover -v`
- 結果: XX tests passed, 0 failed

### ベースラインとの差分
- llm_fetcher.py: 1064行 → XXX行 (−YYY行)

### 注意点・質問
- ...
```

---

## Out-of-scope Items

以下はこの指示書のスコープ外。**実装しないこと**:

1. **Terraform の変更**: `infra/terraform/` 内のリソース定義の変更
2. **プロンプトテンプレートの変更**: `config/*.txt` の内容変更
3. **config.json のスキーマ変更**: 新しいキーの追加や既存キーの削除
4. **依存パッケージの変更**: `requirements.txt` / `requirements-lambda.txt` の変更
5. **news_scraper.py のロジック変更**: スクレイピングロジック、サイト固有セレクタ、日付フィルタリングの変更
6. **bedrock_client.py のロジック変更**: API 呼び出しロジック、リトライロジックの変更
7. **report_html_renderer.py の変更**: HTML 変換ロジックの変更
8. **deploy/ スクリプトのロジック変更**: ビルド・デプロイスクリプトのロジック変更 (ファイルリストの追加は必要)
9. **パフォーマンス最適化**: Lambda のメモリ/タイムアウト設定変更
10. **新機能の追加**: 新しい分析種別、新しい通知チャネル等
11. **S3 パス構造の変更**: 既存の保存先パスの変更
12. **コードフォーマッタの適用**: `black`, `isort` 等の一括適用 (無関係な差分が大量に出るため)

---

## 実装前に確認すべき質問

### Q1. `config.question` 機能の継続利用

`llm_fetcher.py` L862-866 で、`config.question` が設定されている場合に追加の LLM 呼び出しを行う処理がある。
現在の `config/config.json` では `"question": ""` (空文字列) に設定されている。
この機能は今後も残す必要があるか？ 削除候補か？
A.削除する

> **実装担当への指示**: この質問が未回答の場合は、**削除せず残す**こと。

### Q2. `deploy/policies/permissions-policy.json` のハードコード

このファイルにはアカウントID `235217802903` がハードコードされている。Terraform 版 (`main.tf`) では動的に生成されるため、このファイルは手動デプロイ用のレガシー参考資料と思われる。
更新すべきか、注釈を付けるのみにすべきか？
A.更新する

> **実装担当への指示**: この質問が未回答の場合は、**ファイルの先頭にコメントで「このファイルはレガシー参考用。本番は Terraform を参照」と注記するのみ**にすること。

### Q3. `__init_local__` 内の `os.chdir()`

`llm_fetcher.py` L91: `os.chdir(self.script_dir)` がプロセスのカレントディレクトリを変更する副作用がある。
この `os.chdir()` はローカル実行時にのみ到達するが、テスト環境に影響する可能性がある。
削除してパス解決を絶対パスベースに変更してよいか？
A.変更してよい

> **実装担当への指示**: この質問が未回答の場合は、**`os.chdir()` を残す**こと。

---

## 制約事項 (実装担当モデルが必ず守ること)

1. 最初に `git status` を確認し、未コミット変更がある場合はリファクタリングを開始しない
2. 既存の未コミット変更と自分の変更を混ぜない
3. 編集前に Baseline Commands の検証結果を記録する
4. 変更は小さく戻しやすい単位にし、フェーズごとにコミットする
5. 無関係な整形やついでのリファクタリングをしない
6. 既存挙動を勝手に変えない
7. 正しさが不明な場合は実装を止めて質問する
8. 各フェーズごとに検証し、テストが通らなければ次のフェーズに進まない
9. 最後に実行したコマンドと結果を報告する
10. Conventional Commits を使用: `refactor:`, `test:`, `docs:`
11. コミットメッセージは日本語で書く
