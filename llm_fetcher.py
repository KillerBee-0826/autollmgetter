#!/usr/bin/env python3
"""
LLM統合スクリプト
AWS Lambda環境とローカル環境で動作し、Amazon Bedrock (Claude)を使用してニュース分析を実行します。
"""

import sys
import json
import time
import logging
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Dict, List, Optional

try:
    import boto3
    import pytz
    from bedrock_client import BedrockClient
    from botocore.exceptions import ClientError
    from report_html_renderer import render_report_html
except ImportError as e:
    print(f"必要なパッケージがインストールされていません: {e}")
    print("Lambda環境ではboto3が組み込まれています")
    sys.exit(1)

# dotenvはローカル開発時のみ使用（Lambda環境では不要）
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


class LLMFetcher:
    """LLM (Bedrock) を使用して質問の回答を取得するクラス（Lambda対応版）"""

    def __init__(self, config: dict, prompt_template: str, s3_handler, logger: logging.Logger):
        """
        Lambda用初期化（設定をパラメータで受け取る）

        Args:
            config: 設定辞書（S3から読み込み済み）
            prompt_template: プロンプトテンプレート文字列（S3から読み込み済み）
            s3_handler: S3操作ヘルパー（S3Handlerインスタンス）
            logger: ロガーインスタンス（CloudWatch Logs用）
        """
        self.config = config
        self.prompt_template = prompt_template
        self.s3_handler = s3_handler
        self.logger = logger

        self._init_bedrock_client()

    def _init_bedrock_client(self) -> None:
        """設定に基づいてBedrockクライアントを初期化する"""
        provider = self.config.get("llm_provider", "bedrock")
        self.logger.info(f"LLMプロバイダー: {provider}")

        if provider == "bedrock":
            model_id = self.config.get("bedrock_model", "us.anthropic.claude-sonnet-4-5-v2:0")
            region = self.config.get("bedrock_region", "us-east-1")
            max_tokens = self.config.get("bedrock_max_tokens", 4096)
            read_timeout = self.config.get("bedrock_read_timeout", 600)
            connect_timeout = self.config.get("bedrock_connect_timeout", 10)
            retry_max_attempts = self.config.get("bedrock_retry_max_attempts", 0)

            self.model = BedrockClient(
                model_id=model_id,
                region=region,
                logger=self.logger,
                max_tokens=max_tokens,
                read_timeout=read_timeout,
                connect_timeout=connect_timeout,
                retry_max_attempts=retry_max_attempts
            )
            self.logger.info(f"Bedrockクライアント初期化完了: {model_id}")

        else:
            self.logger.error(f"未サポートのLLMプロバイダー: {provider}")
            self.logger.error("現在はBedrock (Claude)のみサポートしています")
            raise ValueError(f"未サポートのLLMプロバイダー: {provider}. config.jsonでllm_provider='bedrock'を設定してください")

    def __init_local__(self, config_path: str = "config/config.json"):
        """
        ローカル環境用初期化（互換性のため残す）

        Args:
            config_path: 設定ファイルのパス
        """
        self.script_dir = Path(__file__).parent.absolute()

        # 環境変数の読み込み
        if load_dotenv:
            load_dotenv()

        # 設定ファイルの読み込み
        self.config = self._load_config(config_path)

        # ログの設定
        self._setup_logging()

        self._init_bedrock_client()

        # プロンプトテンプレートの読み込み
        prompt_path = self.config.get("news_analysis_prompt_path", "config/news_analysis_prompt.txt")
        self.prompt_template = self._load_prompt_template(prompt_path)

        # S3Handlerはローカル環境では不使用
        self.s3_handler = None

        self.logger.info("LLMFetcherを初期化しました（ローカルモード）")

    def _resolve_local_path(self, path: str) -> Path:
        """ローカル実行時の相対パスをプロジェクトルート基準で解決する"""
        resolved_path = Path(path)
        if resolved_path.is_absolute():
            return resolved_path
        script_dir = getattr(self, "script_dir", Path(__file__).parent.absolute())
        return script_dir / resolved_path

    def _load_config(self, config_path: str) -> dict:
        """
        設定ファイルを読み込む

        Args:
            config_path: 設定ファイルのパス

        Returns:
            設定の辞書
        """
        try:
            config_file = self._resolve_local_path(config_path)
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config
        except FileNotFoundError:
            print(f"設定ファイルが見つかりません: {config_path}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"設定ファイルのJSON形式が不正です: {e}")
            sys.exit(1)

    def _load_prompt_template(self, template_path: str) -> str:
        """
        プロンプトテンプレートファイルを読み込む

        Args:
            template_path: プロンプトテンプレートファイルのパス（相対パスまたは絶対パス）

        Returns:
            プロンプトテンプレート文字列
        """
        try:
            if not Path(template_path).is_absolute():
                template_path = self._resolve_local_path(template_path)

            with open(template_path, "r", encoding="utf-8") as f:
                template = f.read()

            if not template.strip():
                self.logger.error(f"プロンプトテンプレートファイルが空です: {template_path}")
                print(f"エラー: プロンプトテンプレートファイルが空です: {template_path}")
                sys.exit(1)

            self.logger.info(f"プロンプトテンプレートを読み込みました: {template_path}")
            return template

        except FileNotFoundError:
            self.logger.error(f"プロンプトテンプレートファイルが見つかりません: {template_path}")
            print(f"エラー: プロンプトテンプレートファイルが見つかりません: {template_path}")
            print(f"news_analysis_prompt.txt ファイルをプロジェクトルート ({self.script_dir}) に配置してください")
            sys.exit(1)
        except UnicodeDecodeError as e:
            self.logger.error(f"プロンプトテンプレートファイルのエンコーディングエラー: {e}")
            print(f"エラー: プロンプトテンプレートファイルはUTF-8エンコーディングで保存してください")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"プロンプトテンプレートの読み込みに失敗しました: {str(e)}")
            print(f"エラー: プロンプトテンプレートの読み込みに失敗しました: {str(e)}")
            sys.exit(1)

    def _setup_logging(self):
        """ログの設定"""
        logs_dir = self._resolve_local_path(self.config["logs_dir"])
        logs_dir.mkdir(exist_ok=True)

        log_file = logs_dir / "news_analyzer.log"

        # ロガーの設定
        self.logger = logging.getLogger("NewsAnalyzer")
        self.logger.setLevel(logging.INFO)

        # ファイルハンドラ
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)

        # コンソールハンドラ
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # フォーマッター
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def fetch_response(self, question: str) -> str:
        """
        LLM (Bedrock) に質問を送信し、回答を取得する（リトライ機能付き）

        Args:
            question: LLMに送信する質問

        Returns:
            LLMからの回答テキスト

        Raises:
            Exception: 最大リトライ回数を超えても失敗した場合
        """
        max_retries = self.config["max_retries"]
        retry_delay = self.config["retry_delay"]

        for attempt in range(max_retries):
            try:
                self.logger.info(f"質問を送信中 (試行 {attempt + 1}/{max_retries})")

                # generate_content()はBedrock対応
                response_text = self.model.generate_content(question)

                if not response_text:
                    raise ValueError("LLMからの回答が空です")

                self.logger.info(
                    f"回答を取得しました (文字数: {len(response_text)})"
                )

                # トークン使用量をログ（Bedrockの場合のみ）
                if hasattr(self.model, 'get_usage_stats'):
                    usage = self.model.get_usage_stats()
                    self.logger.info(
                        f"Token usage: input={usage.get('input_tokens', 0)}, "
                        f"output={usage.get('output_tokens', 0)}"
                    )

                return response_text

            except Exception as e:
                self.logger.warning(
                    f"試行 {attempt + 1}/{max_retries} 失敗: {str(e)}"
                )

                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    self.logger.info(f"{wait_time}秒待機してリトライします")
                    time.sleep(wait_time)
                else:
                    self.logger.error(
                        f"最大リトライ回数({max_retries})に達しました"
                    )
                    raise

    def _analyze_news(self) -> tuple[str, str]:
        """
        ニュース分析を実行

        Returns:
            LLM (Bedrock) による分析結果と保存した記事一覧のS3キー/ファイルパス
        """
        from news_scraper import NewsScraper

        scraper = NewsScraper(self.config, self.logger)
        articles_by_site = scraper.scrape_all_sites()

        # 記事本文を取得（新規追加）
        articles_by_site = scraper.enrich_articles_with_content(articles_by_site)

        # 記事をフォーマット
        formatted = scraper.format_articles_for_llm(articles_by_site)

        # フォーマットされた記事をファイルに保存
        articles_key = self._save_formatted_articles(formatted)

        # 分析プロンプトを生成
        prompt = self._create_news_analysis_prompt(formatted)

        # LLMで分析
        return self.fetch_response(prompt), articles_key

    def _save_formatted_articles(self, formatted_articles: str) -> str:
        """
        フォーマットされた記事を保存（S3またはローカルファイル）

        Args:
            formatted_articles: フォーマットされた記事テキスト

        Returns:
            保存先パス（S3キーまたはファイルパス）
        """
        date_str = self._get_now().strftime("%Y-%m-%d")

        try:
            # Lambda環境（S3Handler使用）
            if self.s3_handler is not None:
                prefix = self._get_output_prefix("daily")
                s3_key = f"{prefix}/{date_str}_articles.txt"
                self.s3_handler.save_text(s3_key, formatted_articles)
                self.logger.info(f"記事一覧をS3に保存しました: s3://{self.s3_handler.bucket_name}/{s3_key}")
                return s3_key

            # ローカル環境（ファイルシステム使用）
            else:
                responses_dir = self._resolve_local_path(self.config["responses_dir"]) / self._get_output_prefix("daily")
                responses_dir.mkdir(parents=True, exist_ok=True)
                output_file = responses_dir / f"{date_str}_articles.txt"

                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(formatted_articles)

                self.logger.info(f"記事一覧をファイルに保存しました: {output_file}")
                return str(output_file)

        except Exception as e:
            self.logger.error(f"記事一覧の保存に失敗しました: {str(e)}")
            raise

    def _get_output_prefix(self, analysis_type: str) -> str:
        """分析種別に対応するS3/ローカル出力プレフィックスを取得する"""
        prefixes = self.config.get("output_prefixes", {})
        return prefixes.get(analysis_type, analysis_type)

    def _get_public_html_prefix(self) -> Optional[str]:
        """公開HTMLコピー用のS3プレフィックスを取得する。無効時はNoneを返す"""
        public_html = self.config.get("public_html", {})
        if not public_html.get("enabled", False):
            return None

        prefix = public_html.get("prefix", "public").strip("/")
        if not prefix:
            self.logger.warning("public_html.prefix が空のため公開HTMLコピーをスキップします")
            return None

        return prefix

    def _save_public_html_copy(self, html_key: str, html_content: str) -> Optional[str]:
        """S3上のHTMLを公開用プレフィックス配下へ追加保存する"""
        if self.s3_handler is None or not html_key.endswith(".html"):
            return None

        public_prefix = self._get_public_html_prefix()
        if public_prefix is None:
            return None

        public_key = f"{public_prefix}/{html_key}"
        self.s3_handler.save_html(public_key, html_content)
        self.logger.info(
            f"公開用HTMLをS3に保存しました: s3://{self.s3_handler.bucket_name}/{public_key}"
        )
        self._refresh_public_html_index(public_prefix)
        return public_key

    def _refresh_public_html_index(self, public_prefix: str) -> None:
        """公開HTML配下のレポート一覧を public/index.html として保存する"""
        if self.s3_handler is None:
            return

        public_prefix = public_prefix.strip("/")
        if not public_prefix:
            return

        index_key = f"{public_prefix}/index.html"
        keys = self.s3_handler.list_objects(f"{public_prefix}/")
        report_keys = [
            key for key in keys
            if key.endswith(".html") and key != index_key
        ]
        index_html = self._render_public_html_index(public_prefix, report_keys)
        self.s3_handler.save_html(index_key, index_html)
        self.logger.info(
            f"公開用HTML一覧をS3に保存しました: s3://{self.s3_handler.bucket_name}/{index_key}"
        )

    def _render_public_html_index(self, public_prefix: str, report_keys: List[str]) -> str:
        """公開HTML一覧ページを生成する"""
        groups = {
            "daily": ("日次", []),
            "weekly": ("週次", []),
            "monthly": ("月次", []),
            "quarterly": ("四半期", []),
            "other": ("その他", []),
        }

        prefix = f"{public_prefix.strip('/')}/"
        for key in report_keys:
            if not key.startswith(prefix):
                continue

            relative_key = key[len(prefix):]
            if not relative_key or relative_key == "index.html":
                continue

            analysis_type = relative_key.split("/", 1)[0]
            group_key = analysis_type if analysis_type in groups else "other"
            groups[group_key][1].append(relative_key)

        sections = []
        for _, (label, links) in groups.items():
            if not links:
                continue

            items = []
            for relative_key in sorted(links, reverse=True):
                display_name = Path(relative_key).stem
                items.append(
                    f'      <li><a href="{escape(relative_key, quote=True)}">'
                    f"{escape(display_name)}</a></li>"
                )

            sections.append(
                f"    <section>\n"
                f"      <h2>{escape(label)}</h2>\n"
                f"      <ul>\n"
                + "\n".join(items)
                + "\n      </ul>\n"
                f"    </section>"
            )

        if not sections:
            sections.append("    <p class=\"muted\">公開済みHTMLレポートはまだありません。</p>")

        generated_at = self._get_now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ニュース分析レポート一覧</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --surface: #ffffff;
      --text: #1f2933;
      --muted: #5f6b7a;
      --border: #d8dde3;
      --accent: #2563a9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.75;
    }}
    main {{
      max-width: 880px;
      min-height: 100vh;
      margin: 0 auto;
      padding: 36px 28px 56px;
      background: var(--surface);
    }}
    h1 {{
      margin: 0 0 8px;
      padding-bottom: 12px;
      border-bottom: 2px solid var(--border);
      font-size: 1.9rem;
      line-height: 1.35;
    }}
    h2 {{
      margin: 1.8em 0 0.65em;
      padding-left: 10px;
      border-left: 4px solid var(--accent);
      font-size: 1.3rem;
      line-height: 1.35;
    }}
    ul {{ margin: 0.75em 0 1em; padding-left: 1.4em; }}
    li {{ margin: 0.28em 0; overflow-wrap: anywhere; }}
    a {{ color: var(--accent); overflow-wrap: anywhere; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 640px) {{
      main {{ padding: 22px 14px 36px; }}
      h1 {{ font-size: 1.55rem; }}
      h2 {{ font-size: 1.2rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>ニュース分析レポート一覧</h1>
    <p class="muted">更新日時: {escape(generated_at)}</p>
{chr(10).join(sections)}
  </main>
</body>
</html>"""

    def _get_now(self) -> datetime:
        """設定されたタイムゾーンの現在時刻を取得する"""
        timezone_name = self.config.get("news_scraping", {}).get("timezone", "Asia/Tokyo")
        tz = pytz.timezone(timezone_name)
        return datetime.now(tz)

    def _get_previous_week_range(self) -> tuple:
        """直前の日曜から土曜までの記事日付範囲を取得する"""
        today = self._get_now().date()
        days_since_sunday = (today.weekday() + 1) % 7
        current_week_sunday = today - timedelta(days=days_since_sunday)
        period_start = current_week_sunday - timedelta(days=7)
        period_end = current_week_sunday - timedelta(days=1)
        return period_start, period_end

    def _get_previous_month_range(self) -> tuple:
        """前月の開始日と終了日を取得する"""
        today = self._get_now().date()
        current_month_start = today.replace(day=1)
        previous_month_end = current_month_start - timedelta(days=1)
        previous_month_start = previous_month_end.replace(day=1)
        return previous_month_start, previous_month_end

    def _get_previous_quarter_range(self) -> tuple:
        """4月始まりの会計年度で直前四半期のラベルと日付範囲を取得する"""
        today = self._get_now().date()
        current_quarter_start_month = ((today.month - 4) % 12) // 3 * 3 + 4
        current_quarter_year = today.year
        if current_quarter_start_month > 12:
            current_quarter_start_month -= 12

        current_quarter_start = today.replace(
            year=current_quarter_year,
            month=current_quarter_start_month,
            day=1
        )
        period_end = current_quarter_start - timedelta(days=1)
        period_start_month = period_end.month - 2
        period_start_year = period_end.year
        if period_start_month <= 0:
            period_start_month += 12
            period_start_year -= 1
        period_start = period_end.replace(year=period_start_year, month=period_start_month, day=1)

        fiscal_year = period_start.year if period_start.month >= 4 else period_start.year - 1
        quarter = ((period_start.month - 4) % 12) // 3 + 1
        quarter_label = f"FY{fiscal_year}-Q{quarter}"
        return quarter_label, period_start, period_end

    def _load_text_if_exists(self, key: str) -> Optional[str]:
        """存在するS3テキストを読み込む。存在しなければNoneを返す"""
        try:
            if self.s3_handler and self.s3_handler.object_exists(key):
                return self.s3_handler.load_text(key)
            return None
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code in ('404', 'NoSuchKey'):
                return None
            raise

    def _load_daily_analysis(self, target_date) -> Optional[str]:
        """記事日付に対応する日次分析をS3から読み込む。移行期間は旧responses/も参照する"""
        article_date_str = target_date.strftime("%Y-%m-%d")
        daily_file_date = target_date + timedelta(days=1)
        daily_file_date_str = daily_file_date.strftime("%Y-%m-%d")
        daily_prefix = self._get_output_prefix("daily")
        candidate_keys = [
            f"{daily_prefix}/{daily_file_date_str}.md",
            f"{daily_prefix}/{daily_file_date_str}.txt",
            f"responses/{daily_file_date_str}.txt"
        ]

        for key in candidate_keys:
            content = self._load_text_if_exists(key)
            if content:
                self.logger.info(f"日次分析を読み込みました: article_date={article_date_str}, key={key}")
                return f"## {article_date_str}\n\n{content}"

        self.logger.warning(f"日次分析が見つかりません: article_date={article_date_str}, file_date={daily_file_date_str}")
        return None

    def _load_weekly_analyses_for_month(self, month_start, month_end) -> str:
        """前月内に終了した週次分析をS3から読み込む"""
        if self.s3_handler is None:
            raise ValueError("月次分析にはS3Handlerが必要です")

        weekly_prefix = self._get_output_prefix("weekly")
        keys = self.s3_handler.list_objects(f"{weekly_prefix}/")
        target_keys_by_period = {}

        for key in keys:
            filename = Path(key).name
            if not (filename.endswith(".md") or filename.endswith(".txt")):
                continue

            try:
                period_part = filename.removesuffix(".md").removesuffix(".txt")
                _, end_date_str = period_part.split("_", 1)
                period_end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            except ValueError:
                self.logger.warning(f"週次分析ファイル名を解析できません: {key}")
                continue

            if month_start <= period_end <= month_end:
                existing_key = target_keys_by_period.get(period_part)
                if existing_key is None or filename.endswith(".md"):
                    target_keys_by_period[period_part] = key

        target_keys = list(target_keys_by_period.values())
        target_keys.sort()
        if not target_keys:
            raise ValueError(
                f"月次分析の入力となる週次分析が見つかりません: {month_start.strftime('%Y-%m')}"
            )

        reports = []
        for key in target_keys:
            content = self.s3_handler.load_text(key)
            reports.append(f"## {Path(key).stem}\n\n{content}")

        self.logger.info(f"月次分析の入力週次レポート数: {len(reports)}")
        return ("\n\n" + "=" * 80 + "\n\n").join(reports)

    def _load_monthly_analyses_for_quarter(self, period_start, period_end) -> str:
        """四半期に含まれる3か月分の月次分析をS3から読み込む"""
        if self.s3_handler is None:
            raise ValueError("四半期分析にはS3Handlerが必要です")

        monthly_prefix = self._get_output_prefix("monthly")
        reports = []
        current_month = period_start.replace(day=1)

        while current_month <= period_end:
            target_month = current_month.strftime("%Y-%m")
            candidate_keys = [
                f"{monthly_prefix}/{target_month}.md",
                f"{monthly_prefix}/{target_month}.txt",
            ]

            for key in candidate_keys:
                content = self._load_text_if_exists(key)
                if content:
                    self.logger.info(f"月次分析を読み込みました: month={target_month}, key={key}")
                    reports.append(f"## {target_month}\n\n{content}")
                    break
            else:
                self.logger.warning(f"月次分析が見つかりません: month={target_month}")

            if current_month.month == 12:
                current_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                current_month = current_month.replace(month=current_month.month + 1)

        if not reports:
            raise ValueError(
                f"四半期分析の入力となる月次分析が見つかりません: "
                f"{period_start.strftime('%Y-%m-%d')} - {period_end.strftime('%Y-%m-%d')}"
            )

        if len(reports) < 3:
            self.logger.warning(f"四半期分析の入力月次レポートが不足しています: {len(reports)}/3")

        self.logger.info(f"四半期分析の入力月次レポート数: {len(reports)}")
        return ("\n\n" + "=" * 80 + "\n\n").join(reports)

    def _create_news_analysis_prompt(self, formatted_articles: str) -> str:
        """
        ニュース分析用のプロンプトを生成

        Args:
            formatted_articles: フォーマットされた記事テキスト

        Returns:
            分析プロンプト
        """
        try:
            return self.prompt_template.format(formatted_articles=formatted_articles)
        except KeyError as e:
            self.logger.error(f"プロンプトテンプレートの変数置換エラー: {e}")
            self.logger.error("テンプレートに {formatted_articles} プレースホルダーが必要です")
            raise ValueError(f"プロンプトテンプレートに必要なプレースホルダーがありません: {e}")

    def _create_periodic_analysis_prompt(self, **kwargs) -> str:
        """
        週次・月次分析用のプロンプトを生成

        Args:
            kwargs: テンプレートに埋め込む変数

        Returns:
            分析プロンプト
        """
        try:
            return self.prompt_template.format(**kwargs)
        except KeyError as e:
            self.logger.error(f"プロンプトテンプレートの変数置換エラー: {e}")
            raise ValueError(f"プロンプトテンプレートに必要なプレースホルダーがありません: {e}")

    def save_response(self, response: str, date_str: Optional[str] = None, section: str = "question") -> str:
        """
        回答を保存（S3またはローカルファイル）

        Args:
            response: 保存する回答テキスト
            date_str: 日付文字列（省略時は今日の日付）
            section: セクション名（"question" or "news_analysis"）

        Returns:
            保存先パス（S3キーまたはファイルパス）
        """
        if date_str is None:
            date_str = self._get_now().strftime("%Y-%m-%d")

        # レスポンス本文を構築
        content_lines = []
        if section == "news_analysis":
            content_lines.append(f"# ニュース分析レポート")
            content_lines.append(f"日時: {self._get_now().strftime('%Y-%m-%d %H:%M:%S')}")
            content_lines.append("-" * 80)
            content_lines.append("")
            content_lines.append(response)
        else:
            content_lines.append(f"質問: {self.config.get('question', '')}")
            content_lines.append(f"日時: {self._get_now().strftime('%Y-%m-%d %H:%M:%S')}")
            content_lines.append("-" * 80)
            content_lines.append("")
            content_lines.append(response)

        content = "\n".join(content_lines)

        try:
            # Lambda環境（S3Handler使用）
            if self.s3_handler is not None:
                prefix = self._get_output_prefix("daily")
                s3_key = f"{prefix}/{date_str}.md"

                # S3では追記が難しいため、既存ファイルを読み込んで結合
                if self.s3_handler.object_exists(s3_key):
                    existing_content = self.s3_handler.load_text(s3_key)
                    content = existing_content + "\n\n" + "=" * 80 + "\n\n" + content

                self.s3_handler.save_markdown(s3_key, content)
                self.logger.info(f"LLM分析レポートをS3に保存しました: s3://{self.s3_handler.bucket_name}/{s3_key}")
                html_key = f"{prefix}/{date_str}.html"
                html_content = render_report_html("ニュース分析レポート", content)
                self.s3_handler.save_html(html_key, html_content)
                self.logger.info(f"LLM分析HTMLをS3に保存しました: s3://{self.s3_handler.bucket_name}/{html_key}")
                self._save_public_html_copy(html_key, html_content)
                if section == "news_analysis":
                    return html_key
                return s3_key

            # ローカル環境（ファイルシステム使用）
            else:
                responses_dir = self._resolve_local_path(self.config["responses_dir"]) / self._get_output_prefix("daily")
                responses_dir.mkdir(parents=True, exist_ok=True)
                output_file = responses_dir / f"{date_str}.md"

                if output_file.exists():
                    existing_content = output_file.read_text(encoding="utf-8")
                    content = existing_content + "\n\n" + "=" * 80 + "\n\n" + content

                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(content)

                self.logger.info(f"回答をファイルに保存しました: {output_file}")
                html_file = responses_dir / f"{date_str}.html"
                html_file.write_text(
                    render_report_html("ニュース分析レポート", content),
                    encoding="utf-8"
                )
                self.logger.info(f"LLM分析HTMLをファイルに保存しました: {html_file}")
                if section == "news_analysis":
                    return str(html_file)
                return str(output_file)

        except Exception as e:
            self.logger.error(f"保存に失敗しました: {str(e)}")
            raise

    def save_periodic_response(
        self,
        response: str,
        analysis_type: str,
        output_name: str,
        title: str
    ) -> str:
        """
        週次・月次分析結果を保存する
        """
        content_lines = [
            f"# {title}",
            f"日時: {self._get_now().strftime('%Y-%m-%d %H:%M:%S')}",
            "-" * 80,
            "",
            response
        ]
        content = "\n".join(content_lines)
        prefix = self._get_output_prefix(analysis_type)

        if self.s3_handler is not None:
            s3_key = f"{prefix}/{output_name}.md"
            self.s3_handler.save_markdown(s3_key, content)
            self.logger.info(f"{title}をS3に保存しました: s3://{self.s3_handler.bucket_name}/{s3_key}")
            html_key = f"{prefix}/{output_name}.html"
            html_content = render_report_html(title, content)
            self.s3_handler.save_html(html_key, html_content)
            self.logger.info(f"{title}HTMLをS3に保存しました: s3://{self.s3_handler.bucket_name}/{html_key}")
            self._save_public_html_copy(html_key, html_content)
            return html_key

        responses_dir = self._resolve_local_path(self.config["responses_dir"]) / prefix
        responses_dir.mkdir(parents=True, exist_ok=True)
        output_file = responses_dir / f"{output_name}.md"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        self.logger.info(f"{title}をファイルに保存しました: {output_file}")
        html_file = responses_dir / f"{output_name}.html"
        html_file.write_text(render_report_html(title, content), encoding="utf-8")
        self.logger.info(f"{title}HTMLをファイルに保存しました: {html_file}")
        return str(html_file)

    def run_daily(self) -> Dict[str, List[str]]:
        """
        日次ニュース分析を実行
        """
        artifacts = {
            "articles": [],
            "analysis": []
        }

        if self.config.get('news_scraping', {}).get('enabled', False):
            self.logger.info("日次ニュース分析を開始")
            news_response, articles_key = self._analyze_news()
            analysis_key = self.save_response(news_response, section="news_analysis")
            artifacts["articles"].append(articles_key)
            artifacts["analysis"].append(analysis_key)
        else:
            self.logger.warning("ニュース分析が無効化されています（config.news_scraping.enabled = false）")

        return artifacts

    def run_weekly(self) -> Dict[str, List[str]]:
        """
        週次ニュース分析を実行
        """
        if self.s3_handler is None:
            raise ValueError("週次分析にはS3Handlerが必要です")

        period_start, period_end = self._get_previous_week_range()
        self.logger.info(f"週次分析対象期間: {period_start} - {period_end}")

        reports = []
        current_date = period_start
        while current_date <= period_end:
            daily_report = self._load_daily_analysis(current_date)
            if daily_report:
                reports.append(daily_report)
            current_date += timedelta(days=1)

        if not reports:
            raise ValueError(f"週次分析の入力となる日次分析が見つかりません: {period_start} - {period_end}")

        if len(reports) < 7:
            self.logger.warning(f"週次分析の入力日次レポートが不足しています: {len(reports)}/7")

        daily_analyses = ("\n\n" + "=" * 80 + "\n\n").join(reports)
        prompt = self._create_periodic_analysis_prompt(
            daily_analyses=daily_analyses,
            period_start=period_start.strftime("%Y-%m-%d"),
            period_end=period_end.strftime("%Y-%m-%d")
        )
        response = self.fetch_response(prompt)
        output_name = f"{period_start.strftime('%Y-%m-%d')}_{period_end.strftime('%Y-%m-%d')}"
        analysis_key = self.save_periodic_response(response, "weekly", output_name, "週次ニュース分析レポート")
        return {
            "articles": [],
            "analysis": [analysis_key]
        }

    def run_monthly(self) -> Dict[str, List[str]]:
        """
        月次ニュース分析を実行
        """
        if self.s3_handler is None:
            raise ValueError("月次分析にはS3Handlerが必要です")

        month_start, month_end = self._get_previous_month_range()
        target_month = month_start.strftime("%Y-%m")
        self.logger.info(f"月次分析対象月: {target_month}")

        weekly_analyses = self._load_weekly_analyses_for_month(month_start, month_end)
        prompt = self._create_periodic_analysis_prompt(
            weekly_analyses=weekly_analyses,
            target_month=target_month,
            period_start=month_start.strftime("%Y-%m-%d"),
            period_end=month_end.strftime("%Y-%m-%d")
        )
        response = self.fetch_response(prompt)
        analysis_key = self.save_periodic_response(response, "monthly", target_month, "月次ニュース分析レポート")
        return {
            "articles": [],
            "analysis": [analysis_key]
        }

    def run_quarterly(self) -> Dict[str, List[str]]:
        """
        四半期ニュース分析を実行
        """
        if self.s3_handler is None:
            raise ValueError("四半期分析にはS3Handlerが必要です")

        quarter_label, period_start, period_end = self._get_previous_quarter_range()
        self.logger.info(f"四半期分析対象期間: {quarter_label} {period_start} - {period_end}")

        monthly_analyses = self._load_monthly_analyses_for_quarter(period_start, period_end)
        prompt = self._create_periodic_analysis_prompt(
            monthly_analyses=monthly_analyses,
            quarter_label=quarter_label,
            period_start=period_start.strftime("%Y-%m-%d"),
            period_end=period_end.strftime("%Y-%m-%d")
        )
        response = self.fetch_response(prompt)
        analysis_key = self.save_periodic_response(response, "quarterly", quarter_label, "四半期ニュース分析レポート")
        return {
            "articles": [],
            "analysis": [analysis_key]
        }

    def _send_email_notification(
        self,
        analysis_type: str,
        artifacts: Dict[str, List[str]]
    ) -> None:
        """設定に応じてSESメール通知を送信する"""
        email_config = self.config.get("email_notification", {})
        if not email_config.get("enabled", False):
            self.logger.info("メール通知は無効化されています")
            return

        enabled_types = email_config.get("enabled_analysis_types", [])
        if analysis_type not in enabled_types:
            self.logger.info(f"メール通知対象外の分析種別です: {analysis_type}")
            return

        if self.s3_handler is None:
            self.logger.warning("S3Handlerがないためメール通知をスキップします")
            return

        has_artifacts = any(keys for keys in artifacts.values())
        if not has_artifacts:
            self.logger.warning("通知対象の生成ファイルがないためメール通知をスキップします")
            return

        try:
            from email_notifier import EmailNotifier

            notifier_config = dict(email_config)
            notifier_config["public_html"] = self.config.get("public_html", {})
            notifier = EmailNotifier(
                config=notifier_config,
                s3_handler=self.s3_handler,
                logger=self.logger
            )
            notifier.send_analysis_notification(
                analysis_type=analysis_type,
                artifacts=artifacts,
                executed_at=self._get_now()
            )
        except Exception as e:
            self.logger.error(f"メール通知に失敗しました: {str(e)}", exc_info=True)
            if email_config.get("fail_on_send_error", False):
                raise

    def run(self, analysis_type: str = "daily") -> bool:
        """
        メイン処理を実行

        Args:
            analysis_type: 分析種別（daily, weekly, monthly, quarterly）

        Returns:
            成功時True、失敗時False
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info(f"News Analyzer (Bedrock Claude) - 処理を開始します: {analysis_type}")

            if analysis_type == "daily":
                artifacts = self.run_daily()
            elif analysis_type == "weekly":
                artifacts = self.run_weekly()
            elif analysis_type == "monthly":
                artifacts = self.run_monthly()
            elif analysis_type == "quarterly":
                artifacts = self.run_quarterly()
            else:
                raise ValueError(f"未サポートの分析種別です: {analysis_type}")

            self._send_email_notification(analysis_type, artifacts)

            self.logger.info("処理が正常に完了しました")
            self.logger.info("=" * 80)
            return True

        except Exception as e:
            self.logger.error(f"処理中にエラーが発生しました: {str(e)}", exc_info=True)
            self.logger.info("=" * 80)
            return False


def main():
    """
    ローカル環境用メイン関数
    Lambda環境では使用しない（lambda_handler.pyを使用）
    """
    try:
        # ローカル環境用の初期化
        fetcher_instance = object.__new__(LLMFetcher)
        fetcher_instance.__init_local__()
        success = fetcher_instance.run()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"致命的なエラー: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 80)
    print("ローカル環境での実行")
    print("注意: Lambda環境ではlambda_handler.pyを使用してください")
    print("=" * 80)
    print()
    main()
