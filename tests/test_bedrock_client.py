import json
import logging
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

import bedrock_news_analyzer.bedrock_client as bedrock_client
from bedrock_news_analyzer.bedrock_client import BedrockClient


class BedrockClientTests(unittest.TestCase):
    def _build_client(self):
        runtime = Mock()
        fake_boto3 = Mock()
        fake_boto3.client.return_value = runtime
        logger = Mock(spec=logging.Logger)

        with patch.object(bedrock_client, "boto3", fake_boto3):
            client = BedrockClient(
                model_id="model-id",
                region="us-east-1",
                logger=logger,
                max_tokens=1234,
                read_timeout=30,
                connect_timeout=5,
                retry_max_attempts=2,
            )

        return client, runtime, fake_boto3, logger

    def test_init_passes_boto3_client_parameters(self):
        client, _, fake_boto3, logger = self._build_client()

        self.assertEqual(client.model_id, "model-id")
        self.assertEqual(client.region, "us-east-1")
        self.assertEqual(client.max_tokens, 1234)
        fake_boto3.client.assert_called_once()
        self.assertEqual(fake_boto3.client.call_args.args[0], "bedrock-runtime")
        self.assertEqual(fake_boto3.client.call_args.kwargs["region_name"], "us-east-1")
        logger.info.assert_called()

    def test_generate_content_returns_text_and_tracks_usage(self):
        client, runtime, _, _ = self._build_client()
        runtime.invoke_model.return_value = {
            "body": BytesIO(json.dumps({
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "tool_use", "text": "ignored"},
                    {"type": "text", "text": " world"},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 3},
                "stop_reason": "end_turn",
            }).encode("utf-8"))
        }

        text = client.generate_content("prompt")

        self.assertEqual(text, "hello world")
        self.assertEqual(client.get_usage_stats(), {"input_tokens": 10, "output_tokens": 3})
        request_body = json.loads(runtime.invoke_model.call_args.kwargs["body"])
        self.assertEqual(request_body["max_tokens"], 1234)
        self.assertEqual(request_body["messages"][0]["content"], "prompt")

    def test_generate_content_logs_warning_when_max_tokens_reached(self):
        client, runtime, _, logger = self._build_client()
        runtime.invoke_model.return_value = {
            "body": BytesIO(json.dumps({
                "content": [{"type": "text", "text": "truncated"}],
                "usage": {"input_tokens": 1, "output_tokens": 2},
                "stop_reason": "max_tokens",
            }).encode("utf-8"))
        }

        self.assertEqual(client.generate_content("prompt"), "truncated")

        self.assertTrue(
            any("max_tokens" in call.args[0] for call in logger.warning.call_args_list)
        )

    def test_generate_content_reraises_throttling_client_error(self):
        client, runtime, _, logger = self._build_client()
        error = ClientError(
            {
                "Error": {
                    "Code": "ThrottlingException",
                    "Message": "rate limited",
                }
            },
            "InvokeModel",
        )
        runtime.invoke_model.side_effect = error

        with self.assertRaises(ClientError):
            client.generate_content("prompt")

        self.assertTrue(
            any("Bedrockレート制限" in call.args[0] for call in logger.warning.call_args_list)
        )

    def test_get_model_info(self):
        client, _, _, _ = self._build_client()

        self.assertEqual(
            client.get_model_info(),
            {"model_id": "model-id", "region": "us-east-1", "max_tokens": 1234},
        )


if __name__ == "__main__":
    unittest.main()
