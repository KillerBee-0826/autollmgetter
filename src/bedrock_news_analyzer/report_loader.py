#!/usr/bin/env python3
"""
週次・月次・四半期分析の入力レポート読み込みを担当するモジュール。
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError


class ReportLoader:
    """前段分析レポートをS3から読み込むクラス"""

    def __init__(self, config: dict, s3_handler, logger):
        self.config = config
        self.s3_handler = s3_handler
        self.logger = logger

    def get_output_prefix(self, analysis_type: str) -> str:
        """分析種別に対応するS3出力プレフィックスを取得する"""
        prefixes = self.config.get("output_prefixes", {})
        return prefixes.get(analysis_type, analysis_type)

    def load_text_if_exists(self, key: str) -> Optional[str]:
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

    def load_daily_analysis(self, target_date) -> Optional[str]:
        """記事日付に対応する日次分析をS3から読み込む。移行期間は旧responses/も参照する"""
        article_date_str = target_date.strftime("%Y-%m-%d")
        daily_file_date = target_date + timedelta(days=1)
        daily_file_date_str = daily_file_date.strftime("%Y-%m-%d")
        daily_prefix = self.get_output_prefix("daily")
        candidate_keys = [
            f"{daily_prefix}/{daily_file_date_str}.md",
            f"{daily_prefix}/{daily_file_date_str}.txt",
            f"responses/{daily_file_date_str}.txt"
        ]

        for key in candidate_keys:
            content = self.load_text_if_exists(key)
            if content:
                self.logger.info(f"日次分析を読み込みました: article_date={article_date_str}, key={key}")
                return f"## {article_date_str}\n\n{content}"

        self.logger.warning(f"日次分析が見つかりません: article_date={article_date_str}, file_date={daily_file_date_str}")
        return None

    def load_weekly_analyses_for_month(self, month_start, month_end) -> str:
        """前月内に終了した週次分析をS3から読み込む"""
        if self.s3_handler is None:
            raise ValueError("月次分析にはS3Handlerが必要です")

        weekly_prefix = self.get_output_prefix("weekly")
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

    def load_monthly_analyses_for_quarter(self, period_start, period_end) -> str:
        """四半期に含まれる3か月分の月次分析をS3から読み込む"""
        if self.s3_handler is None:
            raise ValueError("四半期分析にはS3Handlerが必要です")

        monthly_prefix = self.get_output_prefix("monthly")
        reports = []
        current_month = period_start.replace(day=1)

        while current_month <= period_end:
            target_month = current_month.strftime("%Y-%m")
            candidate_keys = [
                f"{monthly_prefix}/{target_month}.md",
                f"{monthly_prefix}/{target_month}.txt",
            ]

            for key in candidate_keys:
                content = self.load_text_if_exists(key)
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
