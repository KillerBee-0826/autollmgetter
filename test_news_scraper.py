import logging
import sys
import types
import unittest
from datetime import datetime, timedelta, tzinfo
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytz


class _LocalizingTimezone(tzinfo):
    def __init__(self, hours=0):
        self._offset = timedelta(hours=hours)

    def utcoffset(self, dt):
        return self._offset

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "JST" if self._offset == timedelta(hours=9) else "UTC"

    def localize(self, dt):
        return dt.replace(tzinfo=self)


pytz.timezone = Mock(side_effect=lambda name: _LocalizingTimezone(9 if name == "Asia/Tokyo" else 0))
pytz.utc = _LocalizingTimezone(0)

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    class Response:
        pass

    requests_stub.RequestException = RequestException
    requests_stub.Response = Response
    requests_stub.Session = Mock
    adapters_stub = types.ModuleType("requests.adapters")
    adapters_stub.HTTPAdapter = Mock
    requests_stub.adapters = adapters_stub
    sys.modules["requests"] = requests_stub
    sys.modules["requests.adapters"] = adapters_stub

if "feedparser" not in sys.modules:
    feedparser_stub = types.ModuleType("feedparser")
    feedparser_stub.parse = Mock(return_value=SimpleNamespace(entries=[]))
    sys.modules["feedparser"] = feedparser_stub

if "chardet" not in sys.modules:
    chardet_stub = types.ModuleType("chardet")
    chardet_stub.detect = Mock(return_value={"encoding": "utf-8", "confidence": 1.0})
    sys.modules["chardet"] = chardet_stub

if "trafilatura" not in sys.modules:
    trafilatura_stub = types.ModuleType("trafilatura")
    trafilatura_stub.extract = Mock(return_value=None)
    sys.modules["trafilatura"] = trafilatura_stub

if "bs4" not in sys.modules:
    bs4_stub = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, *args, **kwargs):
            pass

        def select(self, *args, **kwargs):
            return []

        def select_one(self, *args, **kwargs):
            return None

    bs4_stub.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = bs4_stub

import news_scraper
from news_scraper import NewsScraper


class NewsScraperTests(unittest.TestCase):
    def _config(self):
        return {
            "max_retries": 1,
            "retry_delay": 0,
            "news_scraping": {
                "user_agent": "test-agent",
                "timezone": "Asia/Tokyo",
                "parallel_workers": 1,
                "timeout_per_site": 1,
                "max_articles_per_site": 2,
                "sites": [
                    {
                        "name": "Site",
                        "url": "https://example.com",
                        "rss_url": "https://example.com/rss",
                    },
                    {
                        "name": "ITmedia",
                        "url": "https://itmedia.example.com",
                        "encoding_fix": "chardet",
                    },
                ],
                "content_fetching": {
                    "min_content_length": 20,
                    "max_content_length": 1000,
                },
            },
        }

    def _build_scraper(self):
        with patch.object(NewsScraper, "_create_session", return_value=Mock()):
            return NewsScraper(self._config(), Mock(spec=logging.Logger))

    def test_init_reads_config_and_sets_target_date(self):
        scraper = self._build_scraper()

        self.assertEqual(scraper.config["news_scraping"]["user_agent"], "test-agent")
        self.assertEqual(scraper.target_date.hour, 0)
        scraper.logger.info.assert_called()

    def test_parse_rss_date_supports_common_formats(self):
        scraper = self._build_scraper()

        self.assertEqual(
            scraper._parse_rss_date("Tue, 19 May 2026 10:30:00 +0900").year,
            2026,
        )
        self.assertEqual(
            scraper._parse_rss_date("2026-05-19T10:30:00+09:00").month,
            5,
        )
        japanese_date = scraper._parse_rss_date("2026年5月19日")
        self.assertEqual(japanese_date.day, 19)
        self.assertIsNotNone(japanese_date.tzinfo)

    def test_is_yesterday_article_compares_in_configured_timezone(self):
        scraper = self._build_scraper()
        tz = pytz.timezone("Asia/Tokyo")
        scraper.target_date = tz.localize(datetime(2026, 5, 19))

        self.assertTrue(scraper._is_yesterday_article(datetime(2026, 5, 19, 12, 0)))
        self.assertTrue(
            scraper._is_yesterday_article(
                pytz.utc.localize(datetime(2026, 5, 18, 15, 30))
            )
        )
        self.assertFalse(scraper._is_yesterday_article(datetime(2026, 5, 18, 23, 59)))

    def test_validate_content_rejects_short_spam_and_garbled_text(self):
        scraper = self._build_scraper()

        self.assertFalse(scraper._validate_content("短い"))
        self.assertFalse(scraper._validate_content("広告 PR スポンサー 提供: 【PR】 Advertisement " * 2))
        self.assertFalse(scraper._validate_content("正常な本文" * 10 + "�" * 20))
        self.assertTrue(scraper._validate_content("これは十分な長さの本文です。" * 5))

    def test_format_articles_for_llm_includes_content_and_fail_marker(self):
        scraper = self._build_scraper()
        scraper.target_date = pytz.timezone("Asia/Tokyo").localize(datetime(2026, 5, 19))

        formatted = scraper.format_articles_for_llm({
            "Site": [
                {
                    "title": "記事1",
                    "url": "https://example.com/1",
                    "description": "概要",
                    "date": scraper.target_date,
                    "content": "本文",
                },
                {
                    "title": "記事2",
                    "url": "https://example.com/2",
                    "description": "",
                    "date": None,
                },
            ],
        })

        self.assertIn("# 2026年05月19日の技術ニュース", formatted)
        self.assertIn("[記事1](https://example.com/1)", formatted)
        self.assertIn("【本文】", formatted)
        self.assertIn("【本文取得失敗】", formatted)
        self.assertIn("**合計記事数**: 2件", formatted)

    def test_fetch_from_rss_filters_to_target_date(self):
        scraper = self._build_scraper()
        tz = pytz.timezone("Asia/Tokyo")
        scraper.target_date = tz.localize(datetime(2026, 5, 19))
        response = SimpleNamespace(content=b"<rss />")
        scraper._fetch_with_retry = Mock(return_value=response)
        entries = [
            SimpleNamespace(
                published="Tue, 19 May 2026 10:30:00 +0900",
                title="対象記事",
                link="https://example.com/target",
                summary="概要",
            ),
            SimpleNamespace(
                published="Mon, 18 May 2026 10:30:00 +0900",
                title="対象外",
                link="https://example.com/old",
                summary="古い",
            ),
        ]

        with patch.object(news_scraper.feedparser, "parse", return_value=SimpleNamespace(entries=entries)):
            articles = scraper._fetch_from_rss("https://example.com/rss", "Site")

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "対象記事")
        self.assertEqual(articles[0]["source"], "Site")

    def test_decode_response_uses_chardet_for_configured_site(self):
        scraper = self._build_scraper()
        response = SimpleNamespace(
            headers={"Content-Type": "text/html"},
            content="こんにちは".encode("cp932"),
            text="wrong",
        )

        with patch.object(news_scraper.chardet, "detect", return_value={"encoding": "cp932", "confidence": 0.99}):
            html = scraper._decode_response(response, "ITmedia")

        self.assertEqual(html, "こんにちは")


if __name__ == "__main__":
    unittest.main()
