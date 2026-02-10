"""
Утилиты для рендера текста в HTML с поддержкой базовой Markdown-разметки.
"""
from __future__ import annotations

import html
import re


def render_html_with_code(text: str) -> str:
    """
    Экранирует текст и конвертирует markdown code fences в HTML <pre><code>.

    Поддерживаются блоки вида ```lang\n...```, язык опционален.
    """
    def _apply_basic_markdown(raw: str) -> str:
        # После html.escape звёздочки/нижние подчёркивания остаются, поэтому конвертируем их в теги
        s = html.escape(raw)

        def bold_sub(match: re.Match[str]) -> str:
            return f"<b>{match.group(1)}</b>"

        def italic_sub(match: re.Match[str]) -> str:
            return f"<i>{match.group(1)}</i>"

        # **bold** и __bold__
        s = re.sub(r"\*\*(.+?)\*\*", bold_sub, s)
        s = re.sub(r"__(.+?)__", bold_sub, s)

        # *italic* и _italic_ (но не внутри двойных символов)
        s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", italic_sub, s)
        s = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", italic_sub, s)
        return s

    parts: list[str] = []
    last = 0
    pattern = re.compile(r"```([a-zA-Z0-9#+-]+)?\n([\s\S]*?)```", re.MULTILINE)

    for match in pattern.finditer(text):
        # Текст до блока кода конвертируем: экранируем + простая Markdown-разметка
        if match.start() > last:
            parts.append(_apply_basic_markdown(text[last:match.start()]))

        lang = match.group(1)
        code = match.group(2).rstrip("\n")
        code_html = html.escape(code)
        if lang:
            parts.append(f"<pre><code class=\"language-{lang}\">{code_html}</code></pre>")
        else:
            parts.append(f"<pre><code>{code_html}</code></pre>")

        last = match.end()

    # Хвост после последнего блока кода
    if last < len(text):
        parts.append(_apply_basic_markdown(text[last:]))

    return "".join(parts)
