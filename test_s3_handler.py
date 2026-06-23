import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

import s3_handler
from s3_handler import S3Handler


class S3HandlerSaveTests(unittest.TestCase):
    def _build_handler(self):
        s3_client = Mock()
        fake_boto3 = Mock()
        fake_boto3.client.return_value = s3_client
        with patch.object(s3_handler, "boto3", fake_boto3):
            handler = S3Handler("bucket")
        return handler, s3_client

    def test_save_text_uses_plain_text_content_type(self):
        handler, s3_client = self._build_handler()

        handler.save_text("daily/report.txt", "本文")

        s3_client.put_object.assert_called_once_with(
            Bucket="bucket",
            Key="daily/report.txt",
            Body="本文".encode("utf-8"),
            ContentType="text/plain; charset=utf-8"
        )

    def test_save_html_uses_html_content_type(self):
        handler, s3_client = self._build_handler()

        handler.save_html("daily/report.html", "<!doctype html>")

        s3_client.put_object.assert_called_once_with(
            Bucket="bucket",
            Key="daily/report.html",
            Body="<!doctype html>".encode("utf-8"),
            ContentType="text/html; charset=utf-8"
        )

    def test_save_markdown_uses_markdown_content_type(self):
        handler, s3_client = self._build_handler()

        handler.save_markdown("daily/report.md", "# 本文")

        s3_client.put_object.assert_called_once_with(
            Bucket="bucket",
            Key="daily/report.md",
            Body="# 本文".encode("utf-8"),
            ContentType="text/markdown; charset=utf-8"
        )

    def test_load_json_decodes_and_parses_object_body(self):
        handler, s3_client = self._build_handler()
        s3_client.get_object.return_value = {
            "Body": BytesIO('{"enabled": true}'.encode("utf-8"))
        }

        self.assertEqual(handler.load_json("config/config.json"), {"enabled": True})
        s3_client.get_object.assert_called_once_with(
            Bucket="bucket",
            Key="config/config.json",
        )

    def test_load_text_decodes_object_body(self):
        handler, s3_client = self._build_handler()
        s3_client.get_object.return_value = {
            "Body": BytesIO("本文".encode("utf-8"))
        }

        self.assertEqual(handler.load_text("daily/report.md"), "本文")

    def test_object_exists_returns_true_for_existing_key(self):
        handler, s3_client = self._build_handler()

        self.assertTrue(handler.object_exists("daily/report.md"))
        s3_client.head_object.assert_called_once_with(
            Bucket="bucket",
            Key="daily/report.md",
        )

    def test_object_exists_returns_false_for_404(self):
        handler, s3_client = self._build_handler()
        s3_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "not found"}},
            "HeadObject",
        )

        self.assertFalse(handler.object_exists("missing.md"))

    def test_list_objects_collects_paginated_keys(self):
        handler, s3_client = self._build_handler()
        s3_client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "daily/1.md"}],
                "IsTruncated": True,
                "NextContinuationToken": "token",
            },
            {
                "Contents": [{"Key": "daily/2.md"}],
                "IsTruncated": False,
            },
        ]

        self.assertEqual(handler.list_objects("daily/"), ["daily/1.md", "daily/2.md"])
        self.assertEqual(s3_client.list_objects_v2.call_count, 2)
        self.assertEqual(
            s3_client.list_objects_v2.call_args_list[1].kwargs["ContinuationToken"],
            "token",
        )


if __name__ == "__main__":
    unittest.main()
