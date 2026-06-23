import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from bedrock_news_analyzer.report_saver import ReportSaver


class ReportSaverTests(unittest.TestCase):
    def _build_saver(self, s3_handler=None):
        config = {
            "responses_dir": "responses",
            "output_prefixes": {
                "daily": "daily",
                "weekly": "weekly",
                "monthly": "monthly",
                "quarterly": "quarterly",
            },
            "public_html": {
                "enabled": True,
                "prefix": "public",
            },
        }
        return ReportSaver(
            config=config,
            s3_handler=s3_handler,
            logger=logging.getLogger("ReportSaverTests"),
            get_now=lambda: datetime(2026, 5, 20, 9, 30, 0),
            resolve_local_path=lambda path: Path(path),
        )

    def test_save_daily_report_saves_markdown_html_and_public_copy(self):
        s3_handler = SimpleNamespace(
            bucket_name="bucket",
            object_exists=Mock(return_value=False),
            load_text=Mock(),
            save_markdown=Mock(),
            save_html=Mock(),
            list_objects=Mock(return_value=[]),
        )
        saver = self._build_saver(s3_handler)

        key = saver.save_daily_report("本文", section="news_analysis")

        self.assertEqual(key, "daily/2026-05-20.html")
        s3_handler.save_markdown.assert_called_once()
        self.assertEqual(s3_handler.save_markdown.call_args.args[0], "daily/2026-05-20.md")
        self.assertEqual(
            [call.args[0] for call in s3_handler.save_html.call_args_list],
            [
                "daily/2026-05-20.html",
                "public/daily/2026-05-20.html",
                "public/index.html",
            ],
        )

    def test_save_periodic_report_uses_analysis_prefix(self):
        s3_handler = SimpleNamespace(
            bucket_name="bucket",
            save_markdown=Mock(),
            save_html=Mock(),
            list_objects=Mock(return_value=[]),
        )
        saver = self._build_saver(s3_handler)

        key = saver.save_periodic_report(
            "週次本文",
            "weekly",
            "2026-05-10_2026-05-16",
            "週次ニュース分析レポート",
        )

        self.assertEqual(key, "weekly/2026-05-10_2026-05-16.html")
        s3_handler.save_markdown.assert_called_once()
        self.assertEqual(
            s3_handler.save_markdown.call_args.args[0],
            "weekly/2026-05-10_2026-05-16.md",
        )

    def test_save_formatted_articles_writes_local_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            saver = self._build_saver()
            saver.config["responses_dir"] = "responses"
            saver.resolve_local_path = lambda path: Path(tmp_dir) / path

            key = saver.save_formatted_articles("記事一覧")

            self.assertEqual(key, str(Path(tmp_dir) / "responses/daily/2026-05-20_articles.txt"))
            self.assertEqual(Path(key).read_text(encoding="utf-8"), "記事一覧")

    def test_render_public_html_index_groups_report_links(self):
        saver = self._build_saver()

        html = saver.render_public_html_index(
            "public",
            [
                "public/daily/2026-05-20.html",
                "public/weekly/2026-05-10_2026-05-16.html",
                "public/index.html",
            ],
        )

        self.assertIn('<a href="daily/2026-05-20.html">2026-05-20</a>', html)
        self.assertIn('<a href="weekly/2026-05-10_2026-05-16.html">2026-05-10_2026-05-16</a>', html)
        self.assertNotIn('href="index.html"', html)


if __name__ == "__main__":
    unittest.main()
