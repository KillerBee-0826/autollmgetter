#!/usr/bin/env python3
"""
分析完了メール通知のディスパッチを担当するモジュール。
"""


def send_email_notification(
    config: dict,
    s3_handler,
    logger,
    analysis_type: str,
    artifacts: dict,
    executed_at,
) -> None:
    """設定に応じてSESメール通知を送信する"""
    email_config = config.get("email_notification", {})
    if not email_config.get("enabled", False):
        logger.info("メール通知は無効化されています")
        return

    enabled_types = email_config.get("enabled_analysis_types", [])
    if analysis_type not in enabled_types:
        logger.info(f"メール通知対象外の分析種別です: {analysis_type}")
        return

    if s3_handler is None:
        logger.warning("S3Handlerがないためメール通知をスキップします")
        return

    has_artifacts = any(keys for keys in artifacts.values())
    if not has_artifacts:
        logger.warning("通知対象の生成ファイルがないためメール通知をスキップします")
        return

    try:
        from .email_notifier import EmailNotifier

        notifier_config = dict(email_config)
        notifier_config["public_html"] = config.get("public_html", {})
        notifier = EmailNotifier(
            config=notifier_config,
            s3_handler=s3_handler,
            logger=logger
        )
        notifier.send_analysis_notification(
            analysis_type=analysis_type,
            artifacts=artifacts,
            executed_at=executed_at
        )
    except Exception as e:
        logger.error(f"メール通知に失敗しました: {str(e)}", exc_info=True)
        if email_config.get("fail_on_send_error", False):
            raise
