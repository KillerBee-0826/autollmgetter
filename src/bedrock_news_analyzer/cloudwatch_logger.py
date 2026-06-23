#!/usr/bin/env python3
"""
CloudWatch Logs用のロガー設定
Lambda環境で標準出力をCloudWatch Logsに自動送信するための設定
"""

import logging
import sys


def setup_cloudwatch_logger(name: str = 'ClaudeFetcher', level: int = logging.INFO) -> logging.Logger:
    """
    CloudWatch Logs用ロガーを設定

    Lambda環境では標準出力が自動的にCloudWatch Logsに送信されるため、
    StreamHandlerを使用してログを出力する。

    Args:
        name: ロガー名
        level: ログレベル（デフォルト: logging.INFO）

    Returns:
        設定済みのロガーインスタンス
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 既存のハンドラーがある場合はクリア（重複防止）
    if logger.handlers:
        logger.handlers.clear()

    # StreamHandlerを追加（Lambda環境では自動的にCloudWatch Logsに送信される）
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # フォーマッターを設定
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # ルートロガーへの伝播を防ぐ（重複ログ防止）
    logger.propagate = False

    return logger


def setup_minimal_logger(name: str = 'ClaudeFetcher', level: int = logging.INFO) -> logging.Logger:
    """
    最小限のロガー設定（Lambda環境用）

    Lambda環境では既にルートロガーにStreamHandlerが設定されているため、
    追加のハンドラーなしでログレベルのみを設定する。

    Args:
        name: ロガー名
        level: ログレベル（デフォルト: logging.INFO）

    Returns:
        設定済みのロガーインスタンス
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


def get_logger(name: str = 'ClaudeFetcher') -> logging.Logger:
    """
    ロガーインスタンスを取得

    既存のロガーを返す。存在しない場合は新規作成。

    Args:
        name: ロガー名

    Returns:
        ロガーインスタンス
    """
    return logging.getLogger(name)
