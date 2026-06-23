import unittest
from html import escape

from bedrock_news_analyzer.report_html_renderer import render_report_html


class ReportHtmlRendererTests(unittest.TestCase):
    def test_renders_headings_paragraphs_and_tsv_table(self):
        html = render_report_html(
            "日次ニュース分析",
            "\n".join([
                "# ニュース分析レポート",
                "日時: 2026-05-19 09:00:00",
                "",
                "### 1. 技術カテゴリ別件数",
                "```tsv",
                "技術カテゴリ\t件数\t代表的な記事タイトル",
                "生成AI\t2\tAI活用の新事例",
                "セキュリティ\t1\thttps://example.com/security",
                "```",
            ])
        )

        self.assertIn("<h1>ニュース分析レポート</h1>", html)
        self.assertIn("<h3>1. 技術カテゴリ別件数</h3>", html)
        self.assertIn("<table>", html)
        self.assertIn("<th>技術カテゴリ</th>", html)
        self.assertIn('<td data-label="技術カテゴリ">生成AI</td>', html)
        self.assertIn(
            '<a href="https://example.com/security" rel="noopener noreferrer">'
            "https://example.com/security</a>",
            html
        )

    def test_renders_markdown_table(self):
        html = render_report_html(
            "日次ニュース分析",
            "\n".join([
                "### 1. 技術カテゴリ別件数",
                "| 技術カテゴリ | 件数 | URL |",
                "| --- | --- | --- |",
                "| 生成AI | 2 | https://example.com/ai |",
                "| セキュリティ | <script>1</script> | https://example.com/security |",
            ])
        )

        self.assertIn("<table>", html)
        self.assertIn("<th>技術カテゴリ</th>", html)
        self.assertIn('<td data-label="技術カテゴリ">生成AI</td>', html)
        self.assertIn("&lt;script&gt;1&lt;/script&gt;", html)
        self.assertIn(
            '<a href="https://example.com/ai" rel="noopener noreferrer">'
            "https://example.com/ai</a>",
            html
        )

    def test_tsv_table_cells_include_escaped_data_labels(self):
        html = render_report_html(
            "表ラベル確認",
            "\n".join([
                "```tsv",
                '技術"カテゴリ\t件数 & 備考',
                "生成AI\t2",
                "```",
            ])
        )

        self.assertIn('<td data-label="技術&quot;カテゴリ">生成AI</td>', html)
        self.assertIn('<td data-label="件数 &amp; 備考">2</td>', html)

    def test_markdown_table_cells_include_escaped_data_labels(self):
        html = render_report_html(
            "表ラベル確認",
            "\n".join([
                "| 技術カテゴリ | 件数 & 備考 |",
                "| --- | --- |",
                "| 生成AI | 2 |",
            ])
        )

        self.assertIn('<td data-label="技術カテゴリ">生成AI</td>', html)
        self.assertIn('<td data-label="件数 &amp; 備考">2</td>', html)

    def test_includes_responsive_table_card_css(self):
        html = render_report_html("CSS確認", "| 列 | |\n| --- | --- |\n| 値 | |")

        self.assertIn("@media (max-width: 640px)", html)
        self.assertIn("content: attr(data-label)", html)
        self.assertIn("tbody, tr, td { display: block; width: 100%; }", html)
        self.assertIn("@media print", html)

    def test_table_css_wraps_long_urls_without_desktop_min_width(self):
        html = render_report_html("CSS確認", "| URL |\n| --- |\n| https://example.com/long/path |")

        self.assertIn("table { width: 100%;", html)
        self.assertIn("table-layout: fixed", html)
        self.assertIn("th, td {", html)
        self.assertIn("overflow-wrap: anywhere", html)
        self.assertIn(".table-wrap a {", html)
        self.assertIn("word-break: break-word", html)
        self.assertNotIn("min-width: 720px", html)
        self.assertNotIn(
            "th { background: var(--table-head); font-weight: 700; white-space: nowrap; }",
            html
        )

    def test_long_url_in_markdown_table_is_linkified_and_wrappable(self):
        long_url = (
            "https://example.com/articles/"
            "2026/05/24/very-long-url-segment-that-should-wrap-inside-table-cell"
            "?utm_source=daily-report&utm_medium=email&utm_campaign=technology-news-analysis"
        )
        html = render_report_html(
            "URL確認",
            "\n".join([
                "| 記事 | URL |",
                "| --- | --- |",
                f"| 長いURLの記事 | {long_url} |",
            ])
        )

        escaped_url = escape(long_url, quote=True)
        self.assertIn(
            f'<a href="{escaped_url}" rel="noopener noreferrer">{escaped_url}</a>',
            html
        )
        self.assertIn("table { width: 100%;", html)
        self.assertIn("overflow-wrap: anywhere", html)
        self.assertNotIn("min-width: 720px", html)

    def test_renders_unordered_and_ordered_lists(self):
        html = render_report_html(
            "リスト確認",
            "\n".join([
                "- 生成AIの掲載が増加",
                "- https://example.com/list",
                "",
                "1. 初期仮説を作る",
                "2. 記事で検証する",
            ])
        )

        self.assertIn("<ul>", html)
        self.assertIn("<li>生成AIの掲載が増加</li>", html)
        self.assertIn("<ol>", html)
        self.assertIn("<li>初期仮説を作る</li>", html)
        self.assertIn(
            '<a href="https://example.com/list" rel="noopener noreferrer">'
            "https://example.com/list</a>",
            html
        )

    def test_escapes_html_inside_report_content(self):
        html = render_report_html(
            "安全性確認",
            "\n".join([
                "# <script>alert(1)</script>",
                "```tsv",
                "列",
                "<img src=x onerror=alert(1)>",
                "```",
            ])
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)

    def test_renders_unknown_fence_as_preformatted_text(self):
        html = render_report_html(
            "コード確認",
            "\n".join([
                "```json",
                '{"key": "<value>"}',
                "```",
            ])
        )

        self.assertIn("<pre><code>", html)
        self.assertIn("&lt;value&gt;", html)


if __name__ == "__main__":
    unittest.main()
