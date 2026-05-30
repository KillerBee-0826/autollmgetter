#!/usr/bin/env python3
"""
AWS Lambda関数のエントリーポイント
EventBridgeスケジュールから呼び出されて、日本の技術ニュースを収集・分析する
"""

import os
import json
import traceback
from typing import Dict, Any

from s3_handler import S3Handler
from cloudwatch_logger import setup_cloudwatch_logger
from llm_fetcher import LLMFetcher


def _get_analysis_type(event: Dict[str, Any]) -> str:
    """EventBridge入力から分析種別を取得する"""
    analysis_type = event.get("analysis_type")
    if analysis_type is None and isinstance(event.get("detail"), dict):
        analysis_type = event["detail"].get("analysis_type")
    return analysis_type or "daily"


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda関数のメインハンドラー

    Args:
        event: EventBridgeイベントまたはテストイベント
        context: Lambda実行コンテキスト

    Returns:
        レスポンス辞書（statusCode, body）
    """
    # CloudWatch Logsロガーを初期化
    logger = setup_cloudwatch_logger()
    logger.info("=" * 80)
    logger.info("Lambda関数実行開始")
    logger.info(f"イベント: {json.dumps(event, ensure_ascii=False)}")

    # 環境変数からS3バケット名を取得
    bucket_name = os.environ.get('S3_BUCKET_NAME')
    if not bucket_name:
        error_msg = "環境変数 S3_BUCKET_NAME が設定されていません"
        logger.error(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({'success': False, 'error': error_msg}, ensure_ascii=False)
        }

    # Bedrock はIAMロール認証のためAPIキー不要

    try:
        # S3Handlerを初期化
        logger.info(f"S3バケットに接続: {bucket_name}")
        s3_handler = S3Handler(bucket_name=bucket_name)

        # config.jsonをS3から読み込み
        logger.info("設定ファイルをS3から読み込み")
        config = s3_handler.load_json('config/config.json')

        # プロバイダーとモデル情報をログ
        provider = config.get('llm_provider', 'bedrock')
        model_key = 'bedrock_model' if provider == 'bedrock' else 'claude_model'  # 将来の拡張を考慮して動的にキーを選択
        logger.info(f"設定ファイル読み込み完了: プロバイダー={provider}, モデル={config.get(model_key)}")

        analysis_type = _get_analysis_type(event)
        if analysis_type not in {"daily", "weekly", "monthly", "quarterly"}:
            error_msg = f"未サポートの分析種別です: {analysis_type}"
            logger.error(error_msg)
            return {
                'statusCode': 400,
                'body': json.dumps({'success': False, 'error': error_msg}, ensure_ascii=False)
            }

        prompt_paths = config.get("prompt_paths", {})
        default_prompt_path = config.get("news_analysis_prompt_path", "config/news_analysis_prompt.txt")
        prompt_path = prompt_paths.get(analysis_type, default_prompt_path)

        # 分析種別に応じたプロンプトをS3から読み込み
        logger.info(f"プロンプトテンプレートをS3から読み込み: analysis_type={analysis_type}, path={prompt_path}")
        prompt_template = s3_handler.load_text(prompt_path)
        logger.info(f"プロンプトテンプレート読み込み完了: {len(prompt_template)} 文字")

        # LLMFetcherを初期化
        logger.info("LLMFetcherを初期化")
        fetcher = LLMFetcher(
            config=config,
            prompt_template=prompt_template,
            s3_handler=s3_handler,
            logger=logger
        )

        # ニュース収集・分析を実行
        logger.info(f"ニュース分析を開始: analysis_type={analysis_type}")
        success = fetcher.run(analysis_type=analysis_type)

        logger.info("=" * 80)
        if success:
            logger.info("Lambda関数実行完了: 成功")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'message': f'{analysis_type} ニュース分析が正常に完了しました'
                }, ensure_ascii=False)
            }
        else:
            logger.error("Lambda関数実行完了: 失敗")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'error': 'ニュース分析処理でエラーが発生しました'
                }, ensure_ascii=False)
            }

    except Exception as e:
        error_msg = f"Lambda関数実行中に致命的なエラーが発生: {str(e)}"
        trace = traceback.format_exc()
        logger.error(error_msg)
        logger.error(trace)
        logger.info("=" * 80)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': 'Lambda関数実行中にエラーが発生しました'
            }, ensure_ascii=False)
        }


def local_test():
    """
    ローカル環境でのテスト実行用関数
    AWS認証情報が設定されている環境で実行可能
    """
    # テストイベント
    test_event = {
        "version": "0",
        "id": "test-12345",
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "time": "2026-04-26T00:00:00Z",
        "region": "ap-northeast-1",
        "resources": [],
        "analysis_type": "daily"
    }

    # モックのLambdaコンテキスト
    class MockContext:
        def __init__(self):
            self.function_name = "claude-news-analyzer"
            self.function_version = "$LATEST"
            self.invoked_function_arn = "arn:aws:lambda:ap-northeast-1:123456789012:function:claude-news-analyzer"
            self.memory_limit_in_mb = 1536
            self.aws_request_id = "test-request-id"
            self.log_group_name = "/aws/lambda/claude-news-analyzer"
            self.log_stream_name = "test-log-stream"

    # Lambda関数を実行
    result = lambda_handler(test_event, MockContext())
    print("\n=== Lambda関数実行結果 ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    # ローカル環境でのテスト実行
    print("ローカル環境でLambda関数をテスト実行します")
    print("注意: S3_BUCKET_NAME 環境変数が必要です")
    print("注意: AWS認証情報（~/.aws/credentials）が正しく設定されている必要があります")
    print()
    local_test()
