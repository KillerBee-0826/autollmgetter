import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

import period_calculator


class PeriodCalculatorTests(unittest.TestCase):
    def test_get_previous_week_range_returns_previous_sunday_to_saturday(self):
        start, end = period_calculator.get_previous_week_range(datetime(2026, 5, 20))

        self.assertEqual(start, date(2026, 5, 10))
        self.assertEqual(end, date(2026, 5, 16))

    def test_get_previous_month_range_returns_previous_calendar_month(self):
        start, end = period_calculator.get_previous_month_range(datetime(2026, 3, 1))

        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))

    def test_get_previous_quarter_range_uses_april_fiscal_year(self):
        cases = [
            (datetime(2026, 7, 1), "FY2026-Q1", date(2026, 4, 1), date(2026, 6, 30)),
            (datetime(2026, 10, 1), "FY2026-Q2", date(2026, 7, 1), date(2026, 9, 30)),
            (datetime(2027, 1, 1), "FY2026-Q3", date(2026, 10, 1), date(2026, 12, 31)),
            (datetime(2026, 4, 1), "FY2025-Q4", date(2026, 1, 1), date(2026, 3, 31)),
        ]

        for now, expected_label, expected_start, expected_end in cases:
            with self.subTest(now=now):
                label, start, end = period_calculator.get_previous_quarter_range(now)

                self.assertEqual(label, expected_label)
                self.assertEqual(start, expected_start)
                self.assertEqual(end, expected_end)

    def test_get_now_uses_configured_timezone(self):
        tz = object()
        now_mock = Mock(return_value=datetime(2026, 5, 20))

        class FakeDateTime:
            now = now_mock

        with patch.object(period_calculator.pytz, "timezone", return_value=tz) as timezone:
            with patch.object(period_calculator, "datetime", FakeDateTime):
                result = period_calculator.get_now({"news_scraping": {"timezone": "Asia/Tokyo"}})

        timezone.assert_called_once_with("Asia/Tokyo")
        now_mock.assert_called_once_with(tz)
        self.assertEqual(result, datetime(2026, 5, 20))


if __name__ == "__main__":
    unittest.main()
