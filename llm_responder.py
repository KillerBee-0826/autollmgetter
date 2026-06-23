#!/usr/bin/env python3
"""
LLM 呼び出しとリトライ制御を担当するモジュール。
"""

import time


def fetch_response(model, config: dict, logger, question: str) -> str:
    """LLM に質問を送信し、回答を取得する"""
    max_retries = config["max_retries"]
    retry_delay = config["retry_delay"]

    for attempt in range(max_retries):
        try:
            logger.info(f"質問を送信中 (試行 {attempt + 1}/{max_retries})")
            response_text = model.generate_content(question)

            if not response_text:
                raise ValueError("LLMからの回答が空です")

            logger.info(f"回答を取得しました (文字数: {len(response_text)})")

            if hasattr(model, 'get_usage_stats'):
                usage = model.get_usage_stats()
                logger.info(
                    f"Token usage: input={usage.get('input_tokens', 0)}, "
                    f"output={usage.get('output_tokens', 0)}"
                )

            return response_text

        except Exception as e:
            logger.warning(f"試行 {attempt + 1}/{max_retries} 失敗: {str(e)}")

            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)
                logger.info(f"{wait_time}秒待機してリトライします")
                time.sleep(wait_time)
            else:
                logger.error(f"最大リトライ回数({max_retries})に達しました")
                raise
