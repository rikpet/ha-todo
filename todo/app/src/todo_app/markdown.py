"""A small, safe Markdown subset for showing Claude's answers in the web UI.

Everything is HTML-escaped first, so nothing in a note can inject markup; only
the constructs Claude typically writes are then turned into HTML: headings,
bold, italics, inline code, code blocks, bullet and numbered lists, tables,
and links (http/https only).
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

_URL_CHARS = r"""[^\s<]+[^\s<.,;:!?)\]'"*]"""
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BARE_URL = re.compile(rf"(?<![\"'>=])(https?://{_URL_CHARS})")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_CODE = re.compile(r"`([^`]+)`")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _inline(text: str) -> str:
    """Inline markup on already-escaped text; code spans are left untouched."""
    parts = _CODE.split(text)
    out = []
    for i, part in enumerate(parts):
        if i % 2:  # inside backticks
            out.append(f"<code>{part}</code>")
            continue
        links: list[str] = []

        def keep(html: str) -> str:
            links.append(html)
            return f"\x00{len(links) - 1}\x00"

        part = _LINK.sub(lambda m: keep(
            f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>'), part)
        part = _BARE_URL.sub(lambda m: keep(
            f'<a href="{m.group(1)}" target="_blank" rel="noopener">{m.group(1)}</a>'), part)
        part = _BOLD.sub(r"<strong>\1</strong>", part)
        part = _ITALIC.sub(r"<em>\1</em>", part)
        part = re.sub("\x00(\\d+)\x00", lambda m: links[int(m.group(1))], part)
        out.append(part)
    return "".join(out)


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def render(text: str) -> Markup:
    lines = str(escape(text.replace("\r\n", "\n"))).split("\n")
    html: list[str] = []
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        if paragraph:
            html.append("<p>" + "<br>".join(_inline(p) for p in paragraph) + "</p>")
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            html.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            i += 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            level = min(len(heading.group(1)) + 2, 6)  # inside a note, keep headings small
            html.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if "|" in stripped and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush()
            head = _cells(stripped)
            rows = []
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            thead = "".join(f"<th>{_inline(c)}</th>" for c in head)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows
            )
            html.append(f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead>'
                        f"<tbody>{tbody}</tbody></table></div>")
            continue
        for pattern, tag in ((_BULLET, "ul"), (_NUMBERED, "ol")):
            if pattern.match(line):
                flush()
                items = []
                while i < len(lines) and pattern.match(lines[i]):
                    items.append(f"<li>{_inline(pattern.match(lines[i]).group(1))}</li>")
                    i += 1
                html.append(f"<{tag}>{''.join(items)}</{tag}>")
                break
        else:
            paragraph.append(stripped)
            i += 1
    flush()
    return Markup("".join(html))
