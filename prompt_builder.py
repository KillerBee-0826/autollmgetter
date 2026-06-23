#!/usr/bin/env python3
"""
分析プロンプトのテンプレート置換を担当するモジュール。
"""


def create_news_analysis_prompt(prompt_template: str, formatted_articles: str, logger) -> str:
    """ニュース分析用のプロンプトを生成する"""
    try:
        return prompt_template.format(formatted_articles=formatted_articles)
    except KeyError as e:
        logger.error(f"プロンプトテンプレートの変数置換エラー: {e}")
        logger.error("テンプレートに {formatted_articles} プレースホルダーが必要です")
        raise ValueError(f"プロンプトテンプレートに必要なプレースホルダーがありません: {e}")


def create_periodic_analysis_prompt(prompt_template: str, logger, **kwargs) -> str:
    """週次・月次・四半期分析用のプロンプトを生成する"""
    try:
        return prompt_template.format(**kwargs)
    except KeyError as e:
        logger.error(f"プロンプトテンプレートの変数置換エラー: {e}")
        raise ValueError(f"プロンプトテンプレートに必要なプレースホルダーがありません: {e}")
