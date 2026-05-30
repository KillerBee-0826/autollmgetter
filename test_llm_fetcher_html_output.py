import logging
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from llm_fetcher import LLMFetcher


class LLMFetcherHtmlOutputTests(unittest.TestCase):
    def _build_fetcher(self):
        fetcher = object.__new__(LLMFetcher)
        fetcher.config = {
            "responses_dir": "responses",
            "output_prefixes": {
                "daily": "daily",
                "weekly": "weekly",
                "monthly": "monthly",
                "quarterly": "quarterly",
            },
            "news_scraping": {
                "timezone": "Asia/Tokyo",
            },
        }
        fetcher.s3_handler = SimpleNamespace(
            bucket_name="bucket",
            object_exists=Mock(return_value=False),
            load_text=Mock(),
            save_text=Mock(),
            save_markdown=Mock(),
            save_html=Mock(),
            list_objects=Mock(return_value=[]),
        )
        fetcher.logger = logging.getLogger("LLMFetcherHtmlOutputTests")
        return fetcher

    def test_save_response_saves_markdown_and_returns_html_key_for_daily_analysis(self):
        fetcher = self._build_fetcher()

        key = fetcher.save_response(
            "# 見出し\n\n| 列 | 値 |\n| --- | --- |\n| A | 1 |",
            date_str="2026-05-19",
            section="news_analysis"
        )

        self.assertEqual(key, "daily/2026-05-19.html")
        fetcher.s3_handler.save_markdown.assert_called_once()
        self.assertEqual(fetcher.s3_handler.save_markdown.call_args.args[0], "daily/2026-05-19.md")
        fetcher.s3_handler.save_text.assert_not_called()
        fetcher.s3_handler.save_html.assert_called_once()
        self.assertEqual(fetcher.s3_handler.save_html.call_args.args[0], "daily/2026-05-19.html")
        self.assertIn("<table>", fetcher.s3_handler.save_html.call_args.args[1])

    def test_save_periodic_response_saves_markdown_and_returns_html_key(self):
        fetcher = self._build_fetcher()

        key = fetcher.save_periodic_response(
            "週間サマリー",
            "weekly",
            "2026-05-10_2026-05-16",
            "週次ニュース分析レポート"
        )

        self.assertEqual(key, "weekly/2026-05-10_2026-05-16.html")
        fetcher.s3_handler.save_markdown.assert_called_once()
        self.assertEqual(
            fetcher.s3_handler.save_markdown.call_args.args[0],
            "weekly/2026-05-10_2026-05-16.md"
        )
        fetcher.s3_handler.save_text.assert_not_called()
        fetcher.s3_handler.save_html.assert_called_once()
        self.assertEqual(
            fetcher.s3_handler.save_html.call_args.args[0],
            "weekly/2026-05-10_2026-05-16.html"
        )

    def test_load_daily_analysis_prefers_markdown_then_legacy_text(self):
        fetcher = self._build_fetcher()
        existing = {"daily/2026-05-19.md": "md本文"}
        fetcher.s3_handler.object_exists.side_effect = lambda key: key in existing
        fetcher.s3_handler.load_text.side_effect = lambda key: existing[key]

        report = fetcher._load_daily_analysis(date(2026, 5, 18))

        self.assertEqual(report, "## 2026-05-18\n\nmd本文")
        fetcher.s3_handler.object_exists.assert_any_call("daily/2026-05-19.md")
        fetcher.s3_handler.load_text.assert_called_once_with("daily/2026-05-19.md")

    def test_load_daily_analysis_falls_back_to_text(self):
        fetcher = self._build_fetcher()
        existing = {"daily/2026-05-19.txt": "txt本文"}
        fetcher.s3_handler.object_exists.side_effect = lambda key: key in existing
        fetcher.s3_handler.load_text.side_effect = lambda key: existing[key]

        report = fetcher._load_daily_analysis(date(2026, 5, 18))

        self.assertEqual(report, "## 2026-05-18\n\ntxt本文")
        self.assertEqual(
            [call.args[0] for call in fetcher.s3_handler.object_exists.call_args_list],
            [
                "daily/2026-05-19.md",
                "daily/2026-05-19.txt",
            ],
        )

    def test_load_weekly_analyses_for_month_prefers_markdown_without_duplicates(self):
        fetcher = self._build_fetcher()
        fetcher.s3_handler.list_objects.return_value = [
            "weekly/2026-05-03_2026-05-09.txt",
            "weekly/2026-05-10_2026-05-16.txt",
            "weekly/2026-05-10_2026-05-16.md",
        ]
        contents = {
            "weekly/2026-05-03_2026-05-09.txt": "旧週次",
            "weekly/2026-05-10_2026-05-16.txt": "重複txt",
            "weekly/2026-05-10_2026-05-16.md": "新週次",
        }
        fetcher.s3_handler.load_text.side_effect = lambda key: contents[key]

        report = fetcher._load_weekly_analyses_for_month(date(2026, 5, 1), date(2026, 5, 31))

        self.assertIn("旧週次", report)
        self.assertIn("新週次", report)
        self.assertNotIn("重複txt", report)
        self.assertEqual(
            [call.args[0] for call in fetcher.s3_handler.load_text.call_args_list],
            [
                "weekly/2026-05-03_2026-05-09.txt",
                "weekly/2026-05-10_2026-05-16.md",
            ],
        )

    def test_previous_quarter_range_uses_april_fiscal_year(self):
        cases = [
            (datetime(2026, 7, 1), "FY2026-Q1", date(2026, 4, 1), date(2026, 6, 30)),
            (datetime(2026, 10, 1), "FY2026-Q2", date(2026, 7, 1), date(2026, 9, 30)),
            (datetime(2027, 1, 1), "FY2026-Q3", date(2026, 10, 1), date(2026, 12, 31)),
            (datetime(2026, 4, 1), "FY2025-Q4", date(2026, 1, 1), date(2026, 3, 31)),
        ]

        for now, expected_label, expected_start, expected_end in cases:
            with self.subTest(now=now):
                fetcher = self._build_fetcher()
                fetcher._get_now = Mock(return_value=now)

                label, period_start, period_end = fetcher._get_previous_quarter_range()

                self.assertEqual(label, expected_label)
                self.assertEqual(period_start, expected_start)
                self.assertEqual(period_end, expected_end)

    def test_load_monthly_analyses_for_quarter_prefers_markdown_and_falls_back_to_text(self):
        fetcher = self._build_fetcher()
        existing = {
            "monthly/2026-04.md": "4月md",
            "monthly/2026-04.txt": "4月txt",
            "monthly/2026-05.txt": "5月txt",
            "monthly/2026-06.md": "6月md",
        }
        fetcher.s3_handler.object_exists.side_effect = lambda key: key in existing
        fetcher.s3_handler.load_text.side_effect = lambda key: existing[key]

        report = fetcher._load_monthly_analyses_for_quarter(date(2026, 4, 1), date(2026, 6, 30))

        self.assertIn("4月md", report)
        self.assertNotIn("4月txt", report)
        self.assertIn("5月txt", report)
        self.assertIn("6月md", report)
        self.assertEqual(
            [call.args[0] for call in fetcher.s3_handler.load_text.call_args_list],
            [
                "monthly/2026-04.md",
                "monthly/2026-05.txt",
                "monthly/2026-06.md",
            ],
        )

    def test_load_monthly_analyses_for_quarter_fails_when_no_inputs_exist(self):
        fetcher = self._build_fetcher()

        with self.assertRaisesRegex(ValueError, "四半期分析の入力となる月次分析が見つかりません"):
            fetcher._load_monthly_analyses_for_quarter(date(2026, 4, 1), date(2026, 6, 30))

    def test_load_monthly_analyses_for_quarter_warns_when_inputs_are_incomplete(self):
        fetcher = self._build_fetcher()
        fetcher.logger = Mock()
        existing = {
            "monthly/2026-04.md": "4月分析",
            "monthly/2026-06.md": "6月分析",
        }
        fetcher.s3_handler.object_exists.side_effect = lambda key: key in existing
        fetcher.s3_handler.load_text.side_effect = lambda key: existing[key]

        report = fetcher._load_monthly_analyses_for_quarter(date(2026, 4, 1), date(2026, 6, 30))

        self.assertIn("4月分析", report)
        self.assertIn("6月分析", report)
        self.assertTrue(
            any("四半期分析の入力月次レポートが不足しています: 2/3" in call.args[0]
                for call in fetcher.logger.warning.call_args_list)
        )

    def test_run_quarterly_creates_prompt_and_returns_html_artifact(self):
        fetcher = self._build_fetcher()
        fetcher.prompt_template = (
            "{quarter_label} {period_start} {period_end}\n{monthly_analyses}"
        )
        fetcher._get_now = Mock(return_value=datetime(2026, 7, 1))
        existing = {
            "monthly/2026-04.md": "4月分析",
            "monthly/2026-05.md": "5月分析",
            "monthly/2026-06.md": "6月分析",
        }
        fetcher.s3_handler.object_exists.side_effect = lambda key: key in existing
        fetcher.s3_handler.load_text.side_effect = lambda key: existing[key]
        fetcher.fetch_response = Mock(return_value="四半期分析")

        artifacts = fetcher.run_quarterly()

        self.assertEqual(artifacts, {"articles": [], "analysis": ["quarterly/FY2026-Q1.html"]})
        sent_prompt = fetcher.fetch_response.call_args.args[0]
        self.assertIn("FY2026-Q1", sent_prompt)
        self.assertIn("2026-04-01", sent_prompt)
        self.assertIn("2026-06-30", sent_prompt)
        self.assertIn("4月分析", sent_prompt)
        self.assertEqual(
            fetcher.s3_handler.save_markdown.call_args.args[0],
            "quarterly/FY2026-Q1.md"
        )
        self.assertEqual(
            fetcher.s3_handler.save_html.call_args.args[0],
            "quarterly/FY2026-Q1.html"
        )

    def test_run_dispatches_quarterly_analysis(self):
        fetcher = self._build_fetcher()
        fetcher.run_quarterly = Mock(return_value={"articles": [], "analysis": ["quarterly/FY2026-Q1.html"]})
        fetcher._send_email_notification = Mock()

        success = fetcher.run("quarterly")

        self.assertTrue(success)
        fetcher.run_quarterly.assert_called_once_with()
        fetcher._send_email_notification.assert_called_once_with(
            "quarterly",
            {"articles": [], "analysis": ["quarterly/FY2026-Q1.html"]}
        )


if __name__ == "__main__":
    unittest.main()
