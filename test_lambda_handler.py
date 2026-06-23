import json
import sys
import types
import unittest
from datetime import timezone
from unittest.mock import Mock, patch

if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = Mock()
    sys.modules["boto3"] = boto3_stub

if "botocore" not in sys.modules:
    botocore_stub = types.ModuleType("botocore")
    botocore_config_stub = types.ModuleType("botocore.config")
    botocore_exceptions_stub = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        pass

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    botocore_config_stub.Config = Config
    botocore_exceptions_stub.ClientError = ClientError
    sys.modules["botocore"] = botocore_stub
    sys.modules["botocore.config"] = botocore_config_stub
    sys.modules["botocore.exceptions"] = botocore_exceptions_stub

if "pytz" not in sys.modules:
    pytz_stub = types.ModuleType("pytz")
    pytz_stub.timezone = Mock(return_value=timezone.utc)
    sys.modules["pytz"] = pytz_stub

import lambda_handler


class LambdaHandlerErrorResponseTests(unittest.TestCase):
    def _invoke_success(self, event, expected_analysis_type, prompt_key):
        logger = Mock()
        s3_handler = Mock()
        s3_handler.load_json.return_value = {
            "llm_provider": "bedrock",
            "bedrock_model": "model",
            "prompt_paths": {
                expected_analysis_type: prompt_key,
            },
        }
        s3_handler.load_text.return_value = "prompt"
        fetcher = Mock()
        fetcher.run.return_value = True

        with patch.dict(lambda_handler.os.environ, {"S3_BUCKET_NAME": "bucket"}, clear=True):
            with patch.object(lambda_handler, "setup_cloudwatch_logger", return_value=logger):
                with patch.object(lambda_handler, "S3Handler", return_value=s3_handler):
                    with patch.object(lambda_handler, "LLMFetcher", return_value=fetcher):
                        response = lambda_handler.lambda_handler(event, Mock())

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["success"], True)
        s3_handler.load_text.assert_called_once_with(prompt_key)
        fetcher.run.assert_called_once_with(analysis_type=expected_analysis_type)

    def test_daily_analysis_type_is_allowed(self):
        self._invoke_success(
            {"analysis_type": "daily"},
            "daily",
            "config/news_analysis_prompt.txt",
        )

    def test_weekly_analysis_type_is_allowed_from_detail(self):
        self._invoke_success(
            {"detail": {"analysis_type": "weekly"}},
            "weekly",
            "config/weekly_news_analysis_prompt.txt",
        )

    def test_monthly_analysis_type_is_allowed(self):
        self._invoke_success(
            {"analysis_type": "monthly"},
            "monthly",
            "config/monthly_news_analysis_prompt.txt",
        )

    def test_quarterly_analysis_type_is_allowed(self):
        logger = Mock()
        s3_handler = Mock()
        s3_handler.load_json.return_value = {
            "llm_provider": "bedrock",
            "bedrock_model": "model",
            "prompt_paths": {
                "quarterly": "config/quarterly_news_analysis_prompt.txt",
            },
        }
        s3_handler.load_text.return_value = "quarterly prompt"
        fetcher = Mock()
        fetcher.run.return_value = True

        with patch.dict(lambda_handler.os.environ, {"S3_BUCKET_NAME": "bucket"}, clear=True):
            with patch.object(lambda_handler, "setup_cloudwatch_logger", return_value=logger):
                with patch.object(lambda_handler, "S3Handler", return_value=s3_handler):
                    with patch.object(lambda_handler, "LLMFetcher", return_value=fetcher):
                        response = lambda_handler.lambda_handler({"analysis_type": "quarterly"}, Mock())

        self.assertEqual(response["statusCode"], 200)
        s3_handler.load_text.assert_called_once_with("config/quarterly_news_analysis_prompt.txt")
        fetcher.run.assert_called_once_with(analysis_type="quarterly")

    def test_unsupported_analysis_type_returns_400(self):
        logger = Mock()
        s3_handler = Mock()
        s3_handler.load_json.return_value = {
            "llm_provider": "bedrock",
            "bedrock_model": "model",
        }

        with patch.dict(lambda_handler.os.environ, {"S3_BUCKET_NAME": "bucket"}, clear=True):
            with patch.object(lambda_handler, "setup_cloudwatch_logger", return_value=logger):
                with patch.object(lambda_handler, "S3Handler", return_value=s3_handler):
                    response = lambda_handler.lambda_handler({"analysis_type": "yearly"}, Mock())

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertEqual(body["success"], False)
        self.assertIn("未サポートの分析種別です: yearly", body["error"])

    def test_unhandled_exception_response_hides_internal_details_and_logs_traceback(self):
        logger = Mock()
        secret_message = "Sensitive AWS detail: arn:aws:s3:::private-bucket"

        with patch.dict(lambda_handler.os.environ, {"S3_BUCKET_NAME": "private-bucket"}, clear=True):
            with patch.object(lambda_handler, "setup_cloudwatch_logger", return_value=logger):
                with patch.object(lambda_handler, "S3Handler", side_effect=RuntimeError(secret_message)):
                    response = lambda_handler.lambda_handler({"analysis_type": "daily"}, Mock())

        self.assertEqual(response["statusCode"], 500)

        body = json.loads(response["body"])
        self.assertEqual(
            body,
            {
                "success": False,
                "error": "Lambda関数実行中にエラーが発生しました",
            },
        )

        response_body = response["body"]
        self.assertNotIn("traceback", body)
        self.assertNotIn(secret_message, response_body)
        self.assertNotIn("RuntimeError", response_body)
        self.assertNotIn("Traceback", response_body)

        error_logs = [call.args[0] for call in logger.error.call_args_list]
        self.assertTrue(any(secret_message in message for message in error_logs))
        self.assertTrue(any("Traceback (most recent call last)" in message for message in error_logs))
        self.assertTrue(any("RuntimeError" in message for message in error_logs))


if __name__ == "__main__":
    unittest.main()
