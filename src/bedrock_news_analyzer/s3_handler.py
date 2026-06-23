#!/usr/bin/env python3
"""
S3操作を抽象化するヘルパークラス
Lambda関数でS3バケットとのファイルI/Oを簡潔に行うためのユーティリティ
"""

import json
import logging
from typing import Any, Dict
from botocore.exceptions import ClientError

try:
    import boto3
except ImportError:
    # ローカル開発環境では警告のみ（Lambda環境では必須）
    logging.warning("boto3がインストールされていません。Lambda環境では必須です。")
    boto3 = None


class S3Handler:
    """S3バケット操作を抽象化するヘルパークラス"""

    def __init__(self, bucket_name: str):
        """
        初期化

        Args:
            bucket_name: S3バケット名
        """
        if boto3 is None:
            raise ImportError("boto3がインストールされていません。pip install boto3を実行してください。")

        self.s3_client = boto3.client('s3')
        self.bucket_name = bucket_name
        self.logger = logging.getLogger("S3Handler")

    def load_json(self, key: str) -> Dict[str, Any]:
        """
        S3からJSONファイルを読み込み

        Args:
            key: S3オブジェクトキー（例: "config/config.json"）

        Returns:
            パースされたJSONオブジェクト

        Raises:
            ClientError: S3アクセスエラー
            json.JSONDecodeError: JSON解析エラー
        """
        try:
            self.logger.info(f"S3からJSONファイルを読み込み: s3://{self.bucket_name}/{key}")
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            content = response['Body'].read().decode('utf-8')
            return json.loads(content)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                self.logger.error(f"S3キーが存在しません: s3://{self.bucket_name}/{key}")
            elif error_code == 'NoSuchBucket':
                self.logger.error(f"S3バケットが存在しません: {self.bucket_name}")
            else:
                self.logger.error(f"S3アクセスエラー: {e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析エラー: {key} - {e}")
            raise

    def load_text(self, key: str) -> str:
        """
        S3からテキストファイルを読み込み

        Args:
            key: S3オブジェクトキー（例: "config/news_analysis_prompt.txt"）

        Returns:
            ファイル内容（文字列）

        Raises:
            ClientError: S3アクセスエラー
        """
        try:
            self.logger.info(f"S3からテキストファイルを読み込み: s3://{self.bucket_name}/{key}")
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response['Body'].read().decode('utf-8')
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                self.logger.error(f"S3キーが存在しません: s3://{self.bucket_name}/{key}")
            elif error_code == 'NoSuchBucket':
                self.logger.error(f"S3バケットが存在しません: {self.bucket_name}")
            else:
                self.logger.error(f"S3アクセスエラー: {e}")
            raise

    def save_text(self, key: str, content: str) -> None:
        """
        S3にテキストファイルを保存

        Args:
            key: S3オブジェクトキー（例: "responses/2026-04-26.txt"）
            content: 保存する内容

        Raises:
            ClientError: S3アクセスエラー
        """
        try:
            self.logger.info(f"S3にテキストファイルを保存: s3://{self.bucket_name}/{key}")
            self._put_text_object(key, content, 'text/plain; charset=utf-8')
            self.logger.info(f"保存完了: s3://{self.bucket_name}/{key} ({len(content)} 文字)")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                self.logger.error(f"S3バケットが存在しません: {self.bucket_name}")
            else:
                self.logger.error(f"S3アクセスエラー: {e}")
            raise

    def save_markdown(self, key: str, content: str) -> None:
        """
        S3にMarkdownファイルを保存

        Args:
            key: S3オブジェクトキー（例: "daily/2026-04-26.md"）
            content: 保存するMarkdown

        Raises:
            ClientError: S3アクセスエラー
        """
        try:
            self.logger.info(f"S3にMarkdownファイルを保存: s3://{self.bucket_name}/{key}")
            self._put_text_object(key, content, 'text/markdown; charset=utf-8')
            self.logger.info(f"保存完了: s3://{self.bucket_name}/{key} ({len(content)} 文字)")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                self.logger.error(f"S3バケットが存在しません: {self.bucket_name}")
            else:
                self.logger.error(f"S3アクセスエラー: {e}")
            raise

    def save_html(self, key: str, content: str) -> None:
        """
        S3にHTMLファイルを保存

        Args:
            key: S3オブジェクトキー（例: "daily/2026-04-26.html"）
            content: 保存するHTML

        Raises:
            ClientError: S3アクセスエラー
        """
        try:
            self.logger.info(f"S3にHTMLファイルを保存: s3://{self.bucket_name}/{key}")
            self._put_text_object(key, content, 'text/html; charset=utf-8')
            self.logger.info(f"保存完了: s3://{self.bucket_name}/{key} ({len(content)} 文字)")
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchBucket':
                self.logger.error(f"S3バケットが存在しません: {self.bucket_name}")
            else:
                self.logger.error(f"S3アクセスエラー: {e}")
            raise

    def _put_text_object(self, key: str, content: str, content_type: str) -> None:
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType=content_type
        )

    def object_exists(self, key: str) -> bool:
        """
        S3オブジェクトが存在するか確認

        Args:
            key: S3オブジェクトキー

        Returns:
            存在する場合True、しない場合False
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                raise

    def list_objects(self, prefix: str) -> list:
        """
        指定されたプレフィックスのオブジェクト一覧を取得

        Args:
            prefix: S3キープレフィックス（例: "responses/"）

        Returns:
            オブジェクトキーのリスト
        """
        try:
            self.logger.info(f"S3オブジェクト一覧を取得: s3://{self.bucket_name}/{prefix}")
            keys = []
            continuation_token = None

            while True:
                params = {
                    "Bucket": self.bucket_name,
                    "Prefix": prefix
                }
                if continuation_token:
                    params["ContinuationToken"] = continuation_token

                response = self.s3_client.list_objects_v2(**params)
                keys.extend(obj['Key'] for obj in response.get('Contents', []))

                if not response.get('IsTruncated'):
                    break

                continuation_token = response.get('NextContinuationToken')

            return keys
        except ClientError as e:
            self.logger.error(f"S3アクセスエラー: {e}")
            raise
