#!/usr/bin/env python3
"""
分析対象期間の計算を担当するモジュール。
"""

from datetime import datetime, timedelta

try:
    import pytz
except ImportError:
    from zoneinfo import ZoneInfo

    class _PytzCompat:
        @staticmethod
        def timezone(timezone_name: str):
            return ZoneInfo(timezone_name)

    pytz = _PytzCompat()


def get_now(config: dict) -> datetime:
    """設定されたタイムゾーンの現在時刻を取得する"""
    timezone_name = config.get("news_scraping", {}).get("timezone", "Asia/Tokyo")
    tz = pytz.timezone(timezone_name)
    return datetime.now(tz)


def get_previous_week_range(now: datetime) -> tuple:
    """直前の日曜から土曜までの記事日付範囲を取得する"""
    today = now.date()
    days_since_sunday = (today.weekday() + 1) % 7
    current_week_sunday = today - timedelta(days=days_since_sunday)
    period_start = current_week_sunday - timedelta(days=7)
    period_end = current_week_sunday - timedelta(days=1)
    return period_start, period_end


def get_previous_month_range(now: datetime) -> tuple:
    """前月の開始日と終了日を取得する"""
    today = now.date()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    return previous_month_start, previous_month_end


def get_previous_quarter_range(now: datetime) -> tuple:
    """4月始まりの会計年度で直前四半期のラベルと日付範囲を取得する"""
    today = now.date()
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
