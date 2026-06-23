#!/usr/bin/env python3
"""
Amazon SESによる分析完了メール通知
CloudFrontで公開されたHTMLレポートURLを共有する。
"""

import logging
from datetime import datetime
from html import escape
from typing import Dict, List, Optional

try:
    import boto3
except ImportError:
    boto3 = None


class EmailNotifier:
    """Amazon SESを使って分析結果の通知メールを送信するクラス"""

    def __init__(
        self,
        config: dict,
        s3_handler,
        logger: Optional[logging.Logger] = None
    ):
        """
        初期化

        Args:
            config: email_notification設定
            s3_handler: S3Handlerインスタンス
            logger: ロガー
        """
        if boto3 is None:
            raise ImportError("boto3がインストールされていません。Lambda環境では必須です。")

        self.config = config
        self.s3_handler = s3_handler
        self.logger = logger or logging.getLogger("EmailNotifier")
        self.ses_client = boto3.client("sesv2", region_name=self.config.get("ses_region", "ap-northeast-1"))

    def send_analysis_notification(
        self,
        analysis_type: str,
        artifacts: Dict[str, List[str]],
        executed_at: datetime
    ) -> None:
        """
        分析完了通知を送信する

        Args:
            analysis_type: 分析種別（daily, weekly, monthly, quarterly）
            artifacts: 通知対象のS3キー一覧
            executed_at: 実行日時
        """
        sender = self.config.get("sender")
        recipients = self.config.get("recipients", [])
        if not sender or not recipients:
            raise ValueError("email_notification.sender と recipients を設定してください")

        subject = self._build_subject(analysis_type, executed_at)
        text_body, html_body = self._build_body(analysis_type, artifacts, executed_at)

        self.logger.info(
            f"SESメール通知を送信します: analysis_type={analysis_type}, recipients={len(recipients)}"
        )
        self.ses_client.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": recipients},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"}
                    }
                }
            }
        )
        self.logger.info("SESメール通知を送信しました")

    def _build_subject(self, analysis_type: str, executed_at: datetime) -> str:
        analysis_label = self._analysis_label(analysis_type)
        date_text = executed_at.strftime("%Y-%m-%d")
        return f"{analysis_label}完了通知 - {date_text}"

    def _build_body(
        self,
        analysis_type: str,
        artifacts: Dict[str, List[str]],
        executed_at: datetime
    ) -> tuple[str, str]:
        analysis_label = self._analysis_label(analysis_type)
        links = self._build_artifact_links(artifacts)

        text_lines = [
            f"{analysis_label}が完了しました。",
            "",
            f"分析種別: {analysis_type}",
            f"実行日時: {executed_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
            "生成ファイル:"
        ]

        for link in links:
            text_lines.append(f"- {link['url']}")

        text_lines.extend([
            "",
            "CloudFront経由で公開されたHTMLレポートです。"
        ])
        text_body = "\n".join(text_lines)

        link_items = "\n".join(
            f'<li><a href="{escape(link["url"], quote=True)}">{escape(link["text"])}</a></li>'
            for link in links
        )
        html_body = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <title>{escape(analysis_label)}完了通知</title>
</head>
<body>
  <p>{escape(analysis_label)}が完了しました。</p>
  <dl>
    <dt>分析種別</dt>
    <dd>{escape(analysis_type)}</dd>
    <dt>実行日時</dt>
    <dd>{escape(executed_at.strftime('%Y-%m-%d %H:%M:%S %Z'))}</dd>
  </dl>
  <p>生成ファイル:</p>
  <ul>
{link_items}
  </ul>
  <p>CloudFront経由で公開されたHTMLレポートです。</p>
</body>
</html>"""
        return text_body, html_body

    def _build_artifact_links(
        self,
        artifacts: Dict[str, List[str]]
    ) -> List[Dict[str, str]]:
        links = []
        for key in artifacts.get("analysis", []):
            if not key.endswith(".html"):
                continue

            links.append({
                "text": "分析結果を開く",
                "url": self._build_cloudfront_url(key)
            })

        links.append({
            "text": "レポート一覧を開く",
            "url": self._build_cloudfront_url("index.html")
        })
        return links

    def _build_cloudfront_url(self, key: str) -> str:
        base_url = self.config.get("public_html", {}).get("base_url", "").strip()
        if not base_url:
            raise ValueError(
                "public_html.base_url を設定してください"
            )

        return f"{base_url.rstrip('/')}/{key.lstrip('/')}"

    def _analysis_label(self, analysis_type: str) -> str:
        labels = {
            "daily": "日次ニュース分析",
            "weekly": "週次ニュース分析",
            "monthly": "月次ニュース分析",
            "quarterly": "四半期ニュース分析"
        }
        return labels.get(analysis_type, analysis_type)
