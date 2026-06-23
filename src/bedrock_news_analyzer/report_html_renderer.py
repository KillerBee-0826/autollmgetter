#!/usr/bin/env python3
"""
分析レポートのテキスト出力を公開用HTMLへ変換するユーティリティ。
外部ライブラリに依存せず、既存プロンプトのMarkdown風見出し、表、リストを扱う。
"""

import re
from html import escape
from typing import List, Optional, Tuple
from urllib.parse import urlparse


URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+")


def render_report_html(title: str, content: str) -> str:
    """分析レポート本文を単体で閲覧できるHTML文書に変換する。"""
    body = _render_blocks(content)
    escaped_title = escape(title)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --surface: #ffffff;
      --text: #1f2933;
      --muted: #5f6b7a;
      --border: #d8dde3;
      --accent: #2563a9;
      --table-head: #eef3f8;
      --table-stripe: #fbfcfd;
      --code-bg: #111827;
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
      max-width: 980px;
      margin: 0 auto;
      padding: 36px 28px 56px;
      background: var(--surface);
      min-height: 100vh;
    }}
    h1, h2, h3, h4 {{
      line-height: 1.35;
      margin: 1.8em 0 0.65em;
    }}
    h1 {{
      margin-top: 0;
      padding-bottom: 12px;
      border-bottom: 2px solid var(--border);
      font-size: 1.9rem;
    }}
    h2 {{ font-size: 1.45rem; border-left: 4px solid var(--accent); padding-left: 10px; }}
    h3 {{ font-size: 1.22rem; }}
    h4 {{ font-size: 1.05rem; color: var(--muted); }}
    p {{ margin: 0.75em 0; overflow-wrap: anywhere; }}
    ul, ol {{ padding-left: 1.4em; margin: 0.75em 0 1em; }}
    li {{ margin: 0.28em 0; overflow-wrap: anywhere; }}
    a {{ color: var(--accent); overflow-wrap: anywhere; }}
    hr {{ border: 0; border-top: 1px solid var(--border); margin: 24px 0; }}
    pre {{
      overflow-x: auto;
      padding: 14px;
      background: var(--code-bg);
      color: #f9fafb;
      border-radius: 6px;
      line-height: 1.5;
      overflow-wrap: normal;
    }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .table-wrap {{
      overflow-x: visible;
      margin: 18px 0 28px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--surface);
    }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 0.94rem; }}
    th, td {{
      border: 1px solid var(--border);
      padding: 9px 11px;
      vertical-align: top;
      text-align: left;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .table-wrap a {{
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    th {{ background: var(--table-head); font-weight: 700; }}
    tr:nth-child(even) td {{ background: var(--table-stripe); }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 820px) {{
      main {{ padding: 28px 20px 44px; }}
      h1 {{ font-size: 1.72rem; }}
      h2 {{ font-size: 1.34rem; }}
      h3 {{ font-size: 1.16rem; }}
    }}
    @media (max-width: 640px) {{
      main {{ padding: 22px 14px 36px; }}
      h1 {{ font-size: 1.55rem; }}
      h2 {{ font-size: 1.25rem; }}
      .table-wrap {{
        overflow: visible;
        border: 0;
        background: transparent;
      }}
      table {{
        min-width: 0;
        border-collapse: separate;
        border-spacing: 0;
        font-size: 0.92rem;
      }}
      thead {{
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }}
      tbody, tr, td {{ display: block; width: 100%; }}
      tr {{
        margin: 0 0 14px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--surface);
      }}
      tr:nth-child(even) td {{ background: transparent; }}
      td {{
        border: 0;
        border-bottom: 1px solid var(--border);
        padding: 10px 12px;
      }}
      td:last-child {{ border-bottom: 0; }}
      td::before {{
        content: attr(data-label);
        display: block;
        margin-bottom: 3px;
        color: var(--muted);
        font-size: 0.78rem;
        font-weight: 700;
        line-height: 1.35;
      }}
    }}
    @media print {{
      body {{ background: #ffffff; }}
      main {{ max-width: none; padding: 0; }}
      .table-wrap {{ border-color: #999999; }}
      a {{ color: #000000; text-decoration: underline; }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>"""


def _render_blocks(content: str) -> str:
    lines = content.splitlines()
    html_parts: List[str] = []
    paragraph_lines: List[str] = []
    list_lines: List[tuple[str, str]] = []
    code_lines: List[str] = []
    in_fence = False
    fence_lang = ""

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if text:
            html_parts.append(f"    <p>{_linkify_escaped(text)}</p>")
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_lines:
            return
        list_type = list_lines[0][0]
        tag = "ol" if list_type == "ol" else "ul"
        items = "\n".join(f"      <li>{_linkify_escaped(text)}</li>" for _, text in list_lines)
        html_parts.append(f"    <{tag}>\n{items}\n    </{tag}>")
        list_lines.clear()

    def flush_text_blocks() -> None:
        flush_paragraph()
        flush_list()

    index = 0
    line_count = len(lines)
    while index < line_count:
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                if fence_lang == "tsv":
                    html_parts.append(_render_tsv_table(code_lines))
                else:
                    html_parts.append(_render_preformatted(code_lines))
                code_lines = []
                fence_lang = ""
                in_fence = False
            else:
                flush_text_blocks()
                fence_lang = stripped.removeprefix("```").strip().lower()
                in_fence = True
            index += 1
            continue

        if in_fence:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            flush_text_blocks()
            index += 1
            continue

        if set(stripped) <= {"-"} and len(stripped) >= 3:
            flush_text_blocks()
            html_parts.append("    <hr>")
            index += 1
            continue

        heading_level = _heading_level(stripped)
        if heading_level:
            flush_text_blocks()
            heading_text = stripped[heading_level + 1:].strip()
            html_parts.append(
                f"    <h{heading_level}>{_linkify_escaped(heading_text)}</h{heading_level}>"
            )
            index += 1
            continue

        if _is_markdown_table_start(lines, index):
            flush_text_blocks()
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < line_count and _looks_like_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            html_parts.append(_render_markdown_table(table_lines))
            continue

        list_item = _parse_list_item(stripped)
        if list_item:
            list_type, text = list_item
            flush_paragraph()
            if list_lines and list_lines[0][0] != list_type:
                flush_list()
            list_lines.append((list_type, text))
            index += 1
            continue

        flush_list()
        paragraph_lines.append(line)
        index += 1

    if in_fence:
        html_parts.append(_render_preformatted(code_lines))
    flush_text_blocks()

    if not html_parts:
        return '    <p class="muted">表示できる本文がありません。</p>'
    return "\n".join(html_parts)


def _heading_level(stripped: str) -> int:
    if not stripped.startswith("#"):
        return 0
    level = len(stripped) - len(stripped.lstrip("#"))
    if 1 <= level <= 4 and len(stripped) > level and stripped[level] == " ":
        return level
    return 0


def _render_tsv_table(lines: List[str]) -> str:
    rows = [line.split("\t") for line in lines if line.strip()]
    if not rows:
        return '    <p class="muted">空の表です。</p>'

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    body_rows = normalized_rows[1:]

    return _render_table(header, body_rows)


def _is_markdown_table_start(lines: List[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _looks_like_table_row(lines[index]) and _is_markdown_separator(lines[index + 1])


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_markdown_separator(line: str) -> bool:
    if not _looks_like_table_row(line):
        return False
    cells = _split_markdown_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_markdown_row(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _render_markdown_table(lines: List[str]) -> str:
    rows = [_split_markdown_row(line) for line in lines if _looks_like_table_row(line)]
    if len(rows) < 2:
        return '    <p class="muted">空の表です。</p>'

    header = rows[0]
    body_rows = rows[2:]
    column_count = len(header)
    normalized_body_rows = [
        row[:column_count] + [""] * (column_count - len(row))
        for row in body_rows
    ]

    return _render_table(header, normalized_body_rows)


def _render_table(header: List[str], body_rows: List[List[str]]) -> str:
    header_html = "".join(f"<th>{_render_cell(cell)}</th>" for cell in header)
    body_html = "\n".join(
        "        <tr>"
        + "".join(
            f'<td data-label="{escape(header[index].strip(), quote=True)}">'
            f"{_render_cell(cell)}</td>"
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in body_rows
    )

    return f"""    <div class="table-wrap">
      <table>
        <thead><tr>{header_html}</tr></thead>
        <tbody>
{body_html}
        </tbody>
      </table>
    </div>"""


def _parse_list_item(stripped: str) -> Optional[Tuple[str, str]]:
    if stripped.startswith("- ") and stripped[2:].strip():
        return "ul", stripped[2:].strip()
    ordered_match = re.match(r"\d+\. (.+)", stripped)
    if ordered_match:
        return "ol", ordered_match.group(1).strip()
    return None


def _render_preformatted(lines: List[str]) -> str:
    return f"    <pre><code>{escape(chr(10).join(lines))}</code></pre>"


def _render_cell(cell: str) -> str:
    text = cell.strip()
    if _is_safe_url(text):
        escaped_url = escape(text, quote=True)
        return f'<a href="{escaped_url}" rel="noopener noreferrer">{escape(text)}</a>'
    return _linkify_escaped(text)


def _linkify_escaped(text: str) -> str:
    result = []
    last_end = 0
    for match in URL_PATTERN.finditer(text):
        url = match.group(0).rstrip("。、),]")
        trailing = match.group(0)[len(url):]
        result.append(escape(text[last_end:match.start()]))
        if _is_safe_url(url):
            escaped_url = escape(url, quote=True)
            result.append(f'<a href="{escaped_url}" rel="noopener noreferrer">{escape(url)}</a>')
        else:
            result.append(escape(url))
        result.append(escape(trailing))
        last_end = match.end()
    result.append(escape(text[last_end:]))
    return "".join(result)


def _is_safe_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
