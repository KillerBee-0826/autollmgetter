#!/usr/bin/env python3
"""
Amazon Bedrock クライアント
Claude Sonnet 4.5 via Bedrock統合用のヘルパークラス
"""

import json
import logging
from typing import Optional

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError as e:
    print(f"必要なパッケージがインストールされていません: {e}")
    print("Lambda環境ではboto3が組み込まれています")
    raise


class BedrockClient:
    """Amazon Bedrockを使用してClaudeと対話するクライアント"""

    def __init__(
        self,
        model_id: str,
        region: str,
        logger: logging.Logger,
        max_tokens: int = 4096,
        read_timeout: int = 600,
        connect_timeout: int = 10,
        retry_max_attempts: int = 0,
    ):
        """
        Bedrockクライアントを初期化

        Args:
            model_id: BedrockモデルID（例: us.anthropic.claude-sonnet-4-5-v2:0）
            region: AWSリージョン（例: us-east-1）
            logger: ロガーインスタンス
            max_tokens: 最大トークン数（デフォルト: 4096）
            read_timeout: レスポンス読み取りタイムアウト秒数
            connect_timeout: 接続タイムアウト秒数
            retry_max_attempts: botocore内部リトライ回数（0で無効）
        """
        self.model_id = model_id
        self.region = region
        self.logger = logger
        self.max_tokens = max_tokens
        self.last_usage = {}

        try:
            self.bedrock_runtime = boto3.client(
                'bedrock-runtime',
                region_name=region,
                config=Config(
                    read_timeout=read_timeout,
                    connect_timeout=connect_timeout,
                    retries={'max_attempts': retry_max_attempts}
                )
            )
            self.logger.info(
                f"Bedrockクライアント初期化完了: {model_id} @ {region} "
                f"(read_timeout={read_timeout}s, connect_timeout={connect_timeout}s, "
                f"retry_max_attempts={retry_max_attempts})"
            )
        except Exception as e:
            self.logger.error(f"Bedrockクライアント初期化エラー: {e}")
            raise

    def generate_content(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Claudeでテキストを生成

        Args:
            prompt: 入力プロンプト
            max_tokens: 最大トークン数（省略時はコンストラクタ値を使用）

        Returns:
            生成されたテキスト

        Raises:
            ClientError: Bedrock APIエラー
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        # Claudeリクエストボディを構築
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        try:
            self.logger.debug(f"Bedrock API呼び出し開始: {self.model_id}")

            # Bedrock APIを呼び出し
            response = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )

            # レスポンスを解析
            response_body = json.loads(response['body'].read())

            # トークン使用量を保存
            self.last_usage = response_body.get('usage', {})
            stop_reason = response_body.get('stop_reason')

            # テキストコンテンツを抽出
            content = response_body.get('content', [])
            if not content:
                raise ValueError("Bedrockからのレスポンスが空です")

            text = ''.join(block.get('text', '') for block in content if block.get('type') == 'text')

            self.logger.debug(f"Bedrock API呼び出し成功: {len(text)} 文字")
            self.logger.info(
                f"Token usage: input={self.last_usage.get('input_tokens', 0)}, "
                f"output={self.last_usage.get('output_tokens', 0)}, "
                f"stop_reason={stop_reason}"
            )
            if stop_reason == 'max_tokens':
                self.logger.warning(
                    "Claudeの出力がmax_tokens上限に到達しました。"
                    "bedrock_max_tokens、入力記事数、プロンプトの要約粒度を見直してください。"
                )

            return text

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            # Bedrock特有のエラーをログ
            if error_code == 'ThrottlingException':
                self.logger.warning(f"Bedrockレート制限: {error_message}")
            elif error_code == 'ModelTimeoutException':
                self.logger.error(f"Bedrockタイムアウト: {error_message}")
            elif error_code == 'ValidationException':
                self.logger.error(f"Bedrockリクエスト検証エラー: {error_message}")
            elif error_code == 'AccessDeniedException':
                self.logger.error(f"Bedrock権限エラー: {error_message}")
                self.logger.error("IAMロールにbedrock:InvokeModel権限が必要です")
            else:
                self.logger.error(f"Bedrockエラー [{error_code}]: {error_message}")

            raise

        except json.JSONDecodeError as e:
            self.logger.error(f"Bedrockレスポンス解析エラー: {e}")
            raise

        except Exception as e:
            self.logger.error(f"予期しないエラー: {e}")
            raise

    def get_usage_stats(self) -> dict:
        """
        最後のAPI呼び出しのトークン使用量を取得

        Returns:
            トークン使用量の辞書 {input_tokens: int, output_tokens: int}
        """
        return self.last_usage.copy()

    def get_model_info(self) -> dict:
        """
        モデル情報を取得

        Returns:
            モデル情報の辞書
        """
        return {
            'model_id': self.model_id,
            'region': self.region,
            'max_tokens': self.max_tokens
        }
