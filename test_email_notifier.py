import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import email_notifier
from email_notifier import EmailNotifier


class FakeBoto3:
    def __init__(self):
        self.clients = {}
        self.client_calls = []

    def client(self, service_name, **kwargs):
        self.client_calls.append((service_name, kwargs))
        if service_name == "sesv2":
            client = Mock()
            self.clients["sesv2"] = client
            return client
        if service_name in ("s3", "secretsmanager"):
            raise AssertionError(f"{service_name} should not be used for CloudFront links")
        raise AssertionError(f"unexpected service: {service_name}")


class EmailNotifierCloudFrontUrlTests(unittest.TestCase):
    def _build_notifier(self, config, fake_boto3=None):
        fake_boto3 = fake_boto3 or FakeBoto3()
        s3_handler = SimpleNamespace(
            bucket_name="bucket",
            s3_client=Mock()
        )
        boto3_patcher = patch.object(email_notifier, "boto3", fake_boto3)
        boto3_patcher.start()
        self.addCleanup(boto3_patcher.stop)
        notifier = EmailNotifier(config=config, s3_handler=s3_handler)
        return notifier, s3_handler, fake_boto3

    def test_daily_notification_links_to_analysis_html_and_index_only(self):
        notifier, s3_handler, fake_boto3 = self._build_notifier({
            "public_html": {
                "base_url": "https://d111111abcdef8.cloudfront.net"
            }
        })

        links = notifier._build_artifact_links({
            "articles": ["daily/2026-05-19_articles.txt"],
            "analysis": ["daily/2026-05-19.html"],
        })

        self.assertEqual(
            links,
            [
                {
                    "text": "分析結果を開く",
                    "url": "https://d111111abcdef8.cloudfront.net/daily/2026-05-19.html",
                },
                {
                    "text": "レポート一覧を開く",
                    "url": "https://d111111abcdef8.cloudfront.net/index.html",
                },
            ]
        )
        self.assertFalse(s3_handler.s3_client.generate_presigned_url.called)
        self.assertNotIn("s3", fake_boto3.clients)
        self.assertNotIn("secretsmanager", fake_boto3.clients)

    def test_periodic_notification_links_to_analysis_html_and_index(self):
        notifier, _, _ = self._build_notifier({
            "public_html": {
                "base_url": "https://reports.example.com"
            }
        })

        links = notifier._build_artifact_links({
            "articles": [],
            "analysis": ["weekly/2026-05-10_2026-05-16.html"],
        })

        self.assertEqual(
            links,
            [
                {
                    "text": "分析結果を開く",
                    "url": "https://reports.example.com/weekly/2026-05-10_2026-05-16.html",
                },
                {
                    "text": "レポート一覧を開く",
                    "url": "https://reports.example.com/index.html",
                },
            ]
        )

    def test_cloudfront_base_url_trailing_slash_is_normalized(self):
        notifier, _, _ = self._build_notifier({
            "public_html": {
                "base_url": "https://reports.example.com/"
            }
        })

        self.assertEqual(
            notifier._build_cloudfront_url("/monthly/2026-05.html"),
            "https://reports.example.com/monthly/2026-05.html"
        )

    def test_non_html_analysis_artifacts_are_not_linked(self):
        notifier, _, _ = self._build_notifier({
            "public_html": {
                "base_url": "https://reports.example.com"
            }
        })

        links = notifier._build_artifact_links({
            "articles": ["daily/2026-05-19_articles.txt"],
            "analysis": ["daily/2026-05-19.md", "daily/2026-05-19.txt"],
        })

        self.assertEqual(
            links,
            [
                {
                    "text": "レポート一覧を開く",
                    "url": "https://reports.example.com/index.html",
                },
            ]
        )

    def test_missing_cloudfront_base_url_fails(self):
        notifier, _, _ = self._build_notifier({
            "public_html": {
                "base_url": ""
            }
        })

        with self.assertRaisesRegex(ValueError, "public_html.base_url"):
            notifier._build_artifact_links({
                "articles": [],
                "analysis": ["daily/2026-05-19.html"],
            })

    def test_send_email_uses_cloudfront_links_without_expiration_text(self):
        fake_boto3 = FakeBoto3()
        notifier, _, _ = self._build_notifier({
            "sender": "sender@example.com",
            "recipients": ["recipient@example.com"],
            "public_html": {
                "base_url": "https://reports.example.com"
            }
        }, fake_boto3)

        notifier.send_analysis_notification(
            analysis_type="daily",
            artifacts={
                "articles": ["daily/2026-05-19_articles.txt"],
                "analysis": ["daily/2026-05-19.html"],
            },
            executed_at=datetime(2026, 5, 19, 9, 30, 0)
        )

        fake_boto3.clients["sesv2"].send_email.assert_called_once()
        message = fake_boto3.clients["sesv2"].send_email.call_args.kwargs["Content"]["Simple"]
        text_body = message["Body"]["Text"]["Data"]
        html_body = message["Body"]["Html"]["Data"]
        self.assertIn("https://reports.example.com/daily/2026-05-19.html", text_body)
        self.assertIn("https://reports.example.com/index.html", text_body)
        self.assertNotIn("articles.txt", text_body)
        self.assertNotIn("URL有効期限", text_body)
        self.assertIn("https://reports.example.com/daily/2026-05-19.html", html_body)
        self.assertNotIn("URL有効期限", html_body)


if __name__ == "__main__":
    unittest.main()
