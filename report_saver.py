#!/usr/bin/env python3
"""
レポート保存と公開HTMLコピーを担当するモジュール。
"""

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable, List, Optional

from report_html_renderer import render_report_html


class ReportSaver:
    """日次・定期レポートと公開HTMLコピーを保存するクラス"""

    def __init__(
        self,
        config: dict,
        s3_handler,
        logger,
        get_now: Callable[[], datetime],
        resolve_local_path: Callable[[str], Path],
    ):
        self.config = config
        self.s3_handler = s3_handler
        self.logger = logger
        self.get_now = get_now
        self.resolve_local_path = resolve_local_path

    def save_formatted_articles(self, formatted_articles: str) -> str:
        """フォーマットされた記事一覧を保存する"""
        date_str = self.get_now().strftime("%Y-%m-%d")

        try:
            if self.s3_handler is not None:
                prefix = self.get_output_prefix("daily")
                s3_key = f"{prefix}/{date_str}_articles.txt"
                self.s3_handler.save_text(s3_key, formatted_articles)
                self.logger.info(f"記事一覧をS3に保存しました: s3://{self.s3_handler.bucket_name}/{s3_key}")
                return s3_key

            responses_dir = self.resolve_local_path(self.config["responses_dir"]) / self.get_output_prefix("daily")
            responses_dir.mkdir(parents=True, exist_ok=True)
            output_file = responses_dir / f"{date_str}_articles.txt"
            output_file.write_text(formatted_articles, encoding="utf-8")

            self.logger.info(f"記事一覧をファイルに保存しました: {output_file}")
            return str(output_file)

        except Exception as e:
            self.logger.error(f"記事一覧の保存に失敗しました: {str(e)}")
            raise

    def get_output_prefix(self, analysis_type: str) -> str:
        """分析種別に対応するS3/ローカル出力プレフィックスを取得する"""
        prefixes = self.config.get("output_prefixes", {})
        return prefixes.get(analysis_type, analysis_type)

    def get_public_html_prefix(self) -> Optional[str]:
        """公開HTMLコピー用のS3プレフィックスを取得する。無効時はNoneを返す"""
        public_html = self.config.get("public_html", {})
        if not public_html.get("enabled", False):
            return None

        prefix = public_html.get("prefix", "public").strip("/")
        if not prefix:
            self.logger.warning("public_html.prefix が空のため公開HTMLコピーをスキップします")
            return None

        return prefix

    def save_public_html_copy(self, html_key: str, html_content: str) -> Optional[str]:
        """S3上のHTMLを公開用プレフィックス配下へ追加保存する"""
        if self.s3_handler is None or not html_key.endswith(".html"):
            return None

        public_prefix = self.get_public_html_prefix()
        if public_prefix is None:
            return None

        public_key = f"{public_prefix}/{html_key}"
        self.s3_handler.save_html(public_key, html_content)
        self.logger.info(
            f"公開用HTMLをS3に保存しました: s3://{self.s3_handler.bucket_name}/{public_key}"
        )
        self.refresh_public_html_index(public_prefix)
        return public_key

    def refresh_public_html_index(self, public_prefix: str) -> None:
        """公開HTML配下のレポート一覧を public/index.html として保存する"""
        if self.s3_handler is None:
            return

        public_prefix = public_prefix.strip("/")
        if not public_prefix:
            return

        index_key = f"{public_prefix}/index.html"
        keys = self.s3_handler.list_objects(f"{public_prefix}/")
        report_keys = [
            key for key in keys
            if key.endswith(".html") and key != index_key
        ]
        index_html = self.render_public_html_index(public_prefix, report_keys)
        self.s3_handler.save_html(index_key, index_html)
        self.logger.info(
            f"公開用HTML一覧をS3に保存しました: s3://{self.s3_handler.bucket_name}/{index_key}"
        )

    def render_public_html_index(self, public_prefix: str, report_keys: List[str]) -> str:
        """公開HTML一覧ページを生成する"""
        groups = {
            "daily": ("日次", []),
            "weekly": ("週次", []),
            "monthly": ("月次", []),
            "quarterly": ("四半期", []),
            "other": ("その他", []),
        }

        prefix = f"{public_prefix.strip('/')}/"
        for key in report_keys:
            if not key.startswith(prefix):
                continue

            relative_key = key[len(prefix):]
            if not relative_key or relative_key == "index.html":
                continue

            analysis_type = relative_key.split("/", 1)[0]
            group_key = analysis_type if analysis_type in groups else "other"
            groups[group_key][1].append(relative_key)

        sections = []
        for _, (label, links) in groups.items():
            if not links:
                continue

            items = []
            for relative_key in sorted(links, reverse=True):
                display_name = Path(relative_key).stem
                items.append(
                    f'      <li><a href="{escape(relative_key, quote=True)}">'
                    f"{escape(display_name)}</a></li>"
                )

            sections.append(
                f"    <section>\n"
                f"      <h2>{escape(label)}</h2>\n"
                f"      <ul>\n"
                + "\n".join(items)
                + "\n      </ul>\n"
                f"    </section>"
            )

        if not sections:
            sections.append("    <p class=\"muted\">公開済みHTMLレポートはまだありません。</p>")

        generated_at = self.get_now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ニュース分析レポート一覧</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --surface: #ffffff;
      --text: #1f2933;
      --muted: #5f6b7a;
      --border: #d8dde3;
      --accent: #2563a9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.75;
    }}
    main {{
      max-width: 880px;
      min-height: 100vh;
      margin: 0 auto;
      padding: 36px 28px 56px;
      background: var(--surface);
    }}
    h1 {{
      margin: 0 0 8px;
      padding-bottom: 12px;
      border-bottom: 2px solid var(--border);
      font-size: 1.9rem;
      line-height: 1.35;
    }}
    h2 {{
      margin: 1.8em 0 0.65em;
      padding-left: 10px;
      border-left: 4px solid var(--accent);
      font-size: 1.3rem;
      line-height: 1.35;
    }}
    ul {{ margin: 0.75em 0 1em; padding-left: 1.4em; }}
    li {{ margin: 0.28em 0; overflow-wrap: anywhere; }}
    a {{ color: var(--accent); overflow-wrap: anywhere; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 640px) {{
      main {{ padding: 22px 14px 36px; }}
      h1 {{ font-size: 1.55rem; }}
      h2 {{ font-size: 1.2rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>ニュース分析レポート一覧</h1>
    <p class="muted">更新日時: {escape(generated_at)}</p>
{chr(10).join(sections)}
  </main>
</body>
</html>"""

    def save_daily_report(
        self,
        response: str,
        date_str: Optional[str] = None,
        section: str = "question",
    ) -> str:
        """日次レポートを保存する"""
        if date_str is None:
            date_str = self.get_now().strftime("%Y-%m-%d")

        content_lines = []
        if section == "news_analysis":
            content_lines.append("# ニュース分析レポート")
            content_lines.append(f"日時: {self.get_now().strftime('%Y-%m-%d %H:%M:%S')}")
            content_lines.append("-" * 80)
            content_lines.append("")
            content_lines.append(response)
        else:
            content_lines.append(f"質問: {self.config.get('question', '')}")
            content_lines.append(f"日時: {self.get_now().strftime('%Y-%m-%d %H:%M:%S')}")
            content_lines.append("-" * 80)
            content_lines.append("")
            content_lines.append(response)

        content = "\n".join(content_lines)

        try:
            if self.s3_handler is not None:
                prefix = self.get_output_prefix("daily")
                s3_key = f"{prefix}/{date_str}.md"

                if self.s3_handler.object_exists(s3_key):
                    existing_content = self.s3_handler.load_text(s3_key)
                    content = existing_content + "\n\n" + "=" * 80 + "\n\n" + content

                self.s3_handler.save_markdown(s3_key, content)
                self.logger.info(f"LLM分析レポートをS3に保存しました: s3://{self.s3_handler.bucket_name}/{s3_key}")
                html_key = f"{prefix}/{date_str}.html"
                html_content = render_report_html("ニュース分析レポート", content)
                self.s3_handler.save_html(html_key, html_content)
                self.logger.info(f"LLM分析HTMLをS3に保存しました: s3://{self.s3_handler.bucket_name}/{html_key}")
                self.save_public_html_copy(html_key, html_content)
                if section == "news_analysis":
                    return html_key
                return s3_key

            responses_dir = self.resolve_local_path(self.config["responses_dir"]) / self.get_output_prefix("daily")
            responses_dir.mkdir(parents=True, exist_ok=True)
            output_file = responses_dir / f"{date_str}.md"

            if output_file.exists():
                existing_content = output_file.read_text(encoding="utf-8")
                content = existing_content + "\n\n" + "=" * 80 + "\n\n" + content

            output_file.write_text(content, encoding="utf-8")

            self.logger.info(f"回答をファイルに保存しました: {output_file}")
            html_file = responses_dir / f"{date_str}.html"
            html_file.write_text(
                render_report_html("ニュース分析レポート", content),
                encoding="utf-8"
            )
            self.logger.info(f"LLM分析HTMLをファイルに保存しました: {html_file}")
            if section == "news_analysis":
                return str(html_file)
            return str(output_file)

        except Exception as e:
            self.logger.error(f"保存に失敗しました: {str(e)}")
            raise

    def save_periodic_report(
        self,
        response: str,
        analysis_type: str,
        output_name: str,
        title: str,
    ) -> str:
        """週次・月次・四半期分析結果を保存する"""
        content_lines = [
            f"# {title}",
            f"日時: {self.get_now().strftime('%Y-%m-%d %H:%M:%S')}",
            "-" * 80,
            "",
            response
        ]
        content = "\n".join(content_lines)
        prefix = self.get_output_prefix(analysis_type)

        if self.s3_handler is not None:
            s3_key = f"{prefix}/{output_name}.md"
            self.s3_handler.save_markdown(s3_key, content)
            self.logger.info(f"{title}をS3に保存しました: s3://{self.s3_handler.bucket_name}/{s3_key}")
            html_key = f"{prefix}/{output_name}.html"
            html_content = render_report_html(title, content)
            self.s3_handler.save_html(html_key, html_content)
            self.logger.info(f"{title}HTMLをS3に保存しました: s3://{self.s3_handler.bucket_name}/{html_key}")
            self.save_public_html_copy(html_key, html_content)
            return html_key

        responses_dir = self.resolve_local_path(self.config["responses_dir"]) / prefix
        responses_dir.mkdir(parents=True, exist_ok=True)
        output_file = responses_dir / f"{output_name}.md"
        output_file.write_text(content, encoding="utf-8")
        self.logger.info(f"{title}をファイルに保存しました: {output_file}")
        html_file = responses_dir / f"{output_name}.html"
        html_file.write_text(render_report_html(title, content), encoding="utf-8")
        self.logger.info(f"{title}HTMLをファイルに保存しました: {html_file}")
        return str(html_file)
