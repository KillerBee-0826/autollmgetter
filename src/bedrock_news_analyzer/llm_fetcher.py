#!/usr/bin/env python3
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    from .bedrock_client import BedrockClient
    from .email_dispatcher import send_email_notification
    from .llm_responder import fetch_response as fetch_llm_response
    from .local_runtime import init_local_fetcher
    from .period_calculator import (
        get_now,
        get_previous_month_range,
        get_previous_quarter_range,
        get_previous_week_range,
    )
    from .prompt_builder import (
        create_news_analysis_prompt,
        create_periodic_analysis_prompt,
    )
    from .report_loader import ReportLoader
    from .report_saver import ReportSaver
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
    def __init__(self, config: dict, prompt_template: str, s3_handler, logger: logging.Logger):
        self.config = config
        self.prompt_template = prompt_template
        self.s3_handler = s3_handler
        self.logger = logger
        self.report_loader = self._create_report_loader()
        self.report_saver = self._create_report_saver()

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
        self.script_dir = Path.cwd()
        init_local_fetcher(self, config_path, load_dotenv)

    def _resolve_local_path(self, path: str) -> Path:
        resolved_path = Path(path)
        if resolved_path.is_absolute():
            return resolved_path
        script_dir = getattr(self, "script_dir", Path(__file__).parent.absolute())
        return script_dir / resolved_path

    def _create_report_saver(self) -> ReportSaver:
        return ReportSaver(
            config=self.config,
            s3_handler=self.s3_handler,
            logger=self.logger,
            get_now=self._get_now,
            resolve_local_path=self._resolve_local_path,
        )

    def _get_report_saver(self) -> ReportSaver:
        self.report_saver = self._create_report_saver()
        return self.report_saver

    def _create_report_loader(self) -> ReportLoader:
        return ReportLoader(
            config=self.config,
            s3_handler=self.s3_handler,
            logger=self.logger,
        )

    def _get_report_loader(self) -> ReportLoader:
        self.report_loader = self._create_report_loader()
        return self.report_loader

    def fetch_response(self, question: str) -> str:
        return fetch_llm_response(self.model, self.config, self.logger, question)

    def _analyze_news(self) -> tuple[str, str]:
        from .news_scraper import NewsScraper

        scraper = NewsScraper(self.config, self.logger)
        articles_by_site = scraper.scrape_all_sites()
        articles_by_site = scraper.enrich_articles_with_content(articles_by_site)
        formatted = scraper.format_articles_for_llm(articles_by_site)
        articles_key = self._save_formatted_articles(formatted)
        prompt = self._create_news_analysis_prompt(formatted)
        return self.fetch_response(prompt), articles_key

    def _save_formatted_articles(self, formatted_articles: str) -> str:
        return self._get_report_saver().save_formatted_articles(formatted_articles)

    def _get_output_prefix(self, analysis_type: str) -> str:
        return self._get_report_saver().get_output_prefix(analysis_type)

    def _get_public_html_prefix(self) -> Optional[str]:
        return self._get_report_saver().get_public_html_prefix()

    def _save_public_html_copy(self, html_key: str, html_content: str) -> Optional[str]:
        return self._get_report_saver().save_public_html_copy(html_key, html_content)

    def _refresh_public_html_index(self, public_prefix: str) -> None:
        self._get_report_saver().refresh_public_html_index(public_prefix)

    def _render_public_html_index(self, public_prefix: str, report_keys: List[str]) -> str:
        return self._get_report_saver().render_public_html_index(public_prefix, report_keys)

    def _get_now(self) -> datetime:
        return get_now(self.config)

    def _get_previous_week_range(self) -> tuple:
        return get_previous_week_range(self._get_now())

    def _get_previous_month_range(self) -> tuple:
        return get_previous_month_range(self._get_now())

    def _get_previous_quarter_range(self) -> tuple:
        return get_previous_quarter_range(self._get_now())

    def _load_text_if_exists(self, key: str) -> Optional[str]:
        return self._get_report_loader().load_text_if_exists(key)

    def _load_daily_analysis(self, target_date) -> Optional[str]:
        return self._get_report_loader().load_daily_analysis(target_date)

    def _load_weekly_analyses_for_month(self, month_start, month_end) -> str:
        return self._get_report_loader().load_weekly_analyses_for_month(month_start, month_end)

    def _load_monthly_analyses_for_quarter(self, period_start, period_end) -> str:
        return self._get_report_loader().load_monthly_analyses_for_quarter(period_start, period_end)

    def _create_news_analysis_prompt(self, formatted_articles: str) -> str:
        return create_news_analysis_prompt(self.prompt_template, formatted_articles, self.logger)

    def _create_periodic_analysis_prompt(self, **kwargs) -> str:
        return create_periodic_analysis_prompt(self.prompt_template, self.logger, **kwargs)

    def save_response(self, response: str, date_str: Optional[str] = None, section: str = "question") -> str:
        return self._get_report_saver().save_daily_report(response, date_str, section)

    def save_periodic_response(
        self,
        response: str,
        analysis_type: str,
        output_name: str,
        title: str
    ) -> str:
        return self._get_report_saver().save_periodic_report(
            response,
            analysis_type,
            output_name,
            title,
        )

    def run_daily(self) -> Dict[str, List[str]]:
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
        send_email_notification(
            config=self.config,
            s3_handler=self.s3_handler,
            logger=self.logger,
            analysis_type=analysis_type,
            artifacts=artifacts,
            executed_at=self._get_now(),
        )

    def run(self, analysis_type: str = "daily") -> bool:
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
    try:
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
    print("注意: Lambda環境では bedrock_news_analyzer.lambda_handler を使用してください")
    print("=" * 80)
    print()
    main()
