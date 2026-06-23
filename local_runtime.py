#!/usr/bin/env python3
"""
LLMFetcher のローカル直接実行時初期化を担当するモジュール。
"""

import json
import logging
import sys


def init_local_fetcher(fetcher, config_path: str, load_dotenv_func) -> None:
    """ローカル実行用に LLMFetcher インスタンスを初期化する"""
    if load_dotenv_func:
        load_dotenv_func()

    fetcher.config = load_config(fetcher, config_path)
    setup_logging(fetcher)
    fetcher._init_bedrock_client()

    prompt_path = fetcher.config.get("news_analysis_prompt_path", "config/news_analysis_prompt.txt")
    fetcher.prompt_template = load_prompt_template(fetcher, prompt_path)

    fetcher.s3_handler = None
    fetcher.report_loader = fetcher._create_report_loader()
    fetcher.report_saver = fetcher._create_report_saver()
    fetcher.logger.info("LLMFetcherを初期化しました（ローカルモード）")


def load_config(fetcher, config_path: str) -> dict:
    """設定ファイルを読み込む"""
    try:
        config_file = fetcher._resolve_local_path(config_path)
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"設定ファイルが見つかりません: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"設定ファイルのJSON形式が不正です: {e}")
        sys.exit(1)


def load_prompt_template(fetcher, template_path: str) -> str:
    """プロンプトテンプレートファイルを読み込む"""
    try:
        template_file = fetcher._resolve_local_path(template_path)
        with open(template_file, "r", encoding="utf-8") as f:
            template = f.read()

        if not template.strip():
            fetcher.logger.error(f"プロンプトテンプレートファイルが空です: {template_file}")
            print(f"エラー: プロンプトテンプレートファイルが空です: {template_file}")
            sys.exit(1)

        fetcher.logger.info(f"プロンプトテンプレートを読み込みました: {template_file}")
        return template

    except FileNotFoundError:
        fetcher.logger.error(f"プロンプトテンプレートファイルが見つかりません: {template_path}")
        print(f"エラー: プロンプトテンプレートファイルが見つかりません: {template_path}")
        print(f"news_analysis_prompt.txt ファイルをプロジェクトルート ({fetcher.script_dir}) に配置してください")
        sys.exit(1)
    except UnicodeDecodeError as e:
        fetcher.logger.error(f"プロンプトテンプレートファイルのエンコーディングエラー: {e}")
        print("エラー: プロンプトテンプレートファイルはUTF-8エンコーディングで保存してください")
        sys.exit(1)
    except Exception as e:
        fetcher.logger.error(f"プロンプトテンプレートの読み込みに失敗しました: {str(e)}")
        print(f"エラー: プロンプトテンプレートの読み込みに失敗しました: {str(e)}")
        sys.exit(1)


def setup_logging(fetcher) -> None:
    """ローカル実行用ログを設定する"""
    logs_dir = fetcher._resolve_local_path(fetcher.config["logs_dir"])
    logs_dir.mkdir(exist_ok=True)

    log_file = logs_dir / "news_analyzer.log"
    fetcher.logger = logging.getLogger("NewsAnalyzer")
    fetcher.logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    fetcher.logger.addHandler(file_handler)
    fetcher.logger.addHandler(console_handler)
