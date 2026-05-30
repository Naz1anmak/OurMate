from src.utils.render_utils import render_html_with_code


def test_markdown_link_becomes_anchor():
    out = render_html_with_code("[Changelog](https://core.telegram.org/bots/api-changelog)")
    assert out == '<a href="https://core.telegram.org/bots/api-changelog">Changelog</a>'


def test_markdown_link_with_underscores_in_url_not_italicized():
    # Подчёркивания в URL не должны превращаться в <i> — ссылка защищена от markdown-правил.
    out = render_html_with_code("[t](https://e.example/a_b_c_d)")
    assert out == '<a href="https://e.example/a_b_c_d">t</a>'
    assert "<i>" not in out


def test_markdown_link_amp_in_url_escaped_for_href():
    out = render_html_with_code("[q](https://e.example/s?a=1&b=2)")
    assert out == '<a href="https://e.example/s?a=1&amp;b=2">q</a>'


def test_plain_text_and_bold_still_work():
    out = render_html_with_code("Это **важно** и обычный текст")
    assert out == "Это <b>важно</b> и обычный текст"


def test_link_inside_bullet_list_renders():
    out = render_html_with_code("• [Bot API](https://core.telegram.org/bots/api)")
    assert out == '• <a href="https://core.telegram.org/bots/api">Bot API</a>'
