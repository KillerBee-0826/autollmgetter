import logging
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from botocore.exceptions import ClientError

from report_loader import ReportLoader


class ReportLoaderTests(unittest.TestCase):
    def _build_loader(self):
        s3_handler = SimpleNamespace(
            object_exists=Mock(return_value=False),
            load_text=Mock(),
            list_objects=Mock(return_value=[]),
        )
        loader = ReportLoader(
            config={
                "output_prefixes": {
                    "daily": "daily",
                    "weekly": "weekly",
                    "monthly": "monthly",
                    "quarterly": "quarterly",
                }
            },
            s3_handler=s3_handler,
            logger=logging.getLogger("ReportLoaderTests"),
        )
        return loader, s3_handler

    def test_load_text_if_exists_returns_none_for_missing_object(self):
        loader, s3_handler = self._build_loader()
        s3_handler.object_exists.return_value = False

        self.assertIsNone(loader.load_text_if_exists("daily/missing.md"))
        s3_handler.load_text.assert_not_called()

    def test_load_text_if_exists_treats_nosuchkey_as_missing(self):
        loader, s3_handler = self._build_loader()
        s3_handler.object_exists.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
            "HeadObject",
        )

        self.assertIsNone(loader.load_text_if_exists("daily/missing.md"))

    def test_load_daily_analysis_prefers_markdown_then_text_then_legacy(self):
        loader, s3_handler = self._build_loader()
        existing = {"daily/2026-05-20.md": "md本文"}
        s3_handler.object_exists.side_effect = lambda key: key in existing
        s3_handler.load_text.side_effect = lambda key: existing[key]

        report = loader.load_daily_analysis(date(2026, 5, 19))

        self.assertEqual(report, "## 2026-05-19\n\nmd本文")
        s3_handler.load_text.assert_called_once_with("daily/2026-05-20.md")

    def test_load_weekly_analyses_for_month_prefers_markdown_without_duplicates(self):
        loader, s3_handler = self._build_loader()
        s3_handler.list_objects.return_value = [
            "weekly/2026-05-03_2026-05-09.txt",
            "weekly/2026-05-10_2026-05-16.txt",
            "weekly/2026-05-10_2026-05-16.md",
        ]
        contents = {
            "weekly/2026-05-03_2026-05-09.txt": "旧週次",
            "weekly/2026-05-10_2026-05-16.txt": "重複txt",
            "weekly/2026-05-10_2026-05-16.md": "新週次",
        }
        s3_handler.load_text.side_effect = lambda key: contents[key]

        report = loader.load_weekly_analyses_for_month(date(2026, 5, 1), date(2026, 5, 31))

        self.assertIn("旧週次", report)
        self.assertIn("新週次", report)
        self.assertNotIn("重複txt", report)

    def test_load_monthly_analyses_for_quarter_prefers_markdown_and_falls_back_to_text(self):
        loader, s3_handler = self._build_loader()
        existing = {
            "monthly/2026-04.md": "4月md",
            "monthly/2026-04.txt": "4月txt",
            "monthly/2026-05.txt": "5月txt",
            "monthly/2026-06.md": "6月md",
        }
        s3_handler.object_exists.side_effect = lambda key: key in existing
        s3_handler.load_text.side_effect = lambda key: existing[key]

        report = loader.load_monthly_analyses_for_quarter(date(2026, 4, 1), date(2026, 6, 30))

        self.assertIn("4月md", report)
        self.assertNotIn("4月txt", report)
        self.assertIn("5月txt", report)
        self.assertIn("6月md", report)


if __name__ == "__main__":
    unittest.main()
