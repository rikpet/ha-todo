from todo_app.markdown import render


def test_escapes_html_first():
    out = render('<script>alert(1)</script> <img src=x onerror="y">')
    assert "<script>" not in out and "<img" not in out
    assert "&lt;script&gt;" in out


def test_links_only_http_and_cannot_break_out():
    out = render('[click](javascript:alert(1)) [ok](https://a.se/x?a=1&b=2) see https://b.se/y.')
    assert 'href="javascript' not in out and "[click](javascript:alert(1))" in out
    assert 'href="https://a.se/x?a=1&amp;b=2"' in out
    assert 'href="https://b.se/y"' in out  # trailing dot is not part of the URL
    assert render('https://x.se/"onmouseover="a').count('"onmouseover') == 0


def test_bold_italic_code():
    out = render("**Tibber** is *cheap*, run `todo list` and 5 * 3 * 2")
    assert "<strong>Tibber</strong>" in out and "<em>cheap</em>" in out
    assert "<code>todo list</code>" in out and "5 * 3 * 2" in out


def test_code_span_is_not_formatted():
    assert "<code>**x**</code>" in render("`**x**`")


def test_lists_and_headings():
    out = render("## Plan\n- one\n- two\n\n1. first\n2. second")
    assert "<h4>Plan</h4>" in out
    assert "<ul><li>one</li><li>two</li></ul>" in out
    assert "<ol><li>first</li><li>second</li></ol>" in out


def test_table():
    out = render("| Bolag | Öre |\n|---|---:|\n| Tibber | 89 |\n| Fortum | 94 |\nefter")
    assert "<th>Bolag</th><th>Öre</th>" in out
    assert "<tr><td>Tibber</td><td>89</td></tr><tr><td>Fortum</td><td>94</td></tr>" in out
    assert out.endswith("<p>efter</p>")


def test_code_block_kept_verbatim_and_escaped():
    out = render("```\n<b>raw</b>\n  indented **not bold**\n```")
    assert "<pre><code>&lt;b&gt;raw&lt;/b&gt;\n  indented **not bold**</code></pre>" == out


def test_paragraphs_and_line_breaks():
    assert render("a\nb\n\nc") == "<p>a<br>b</p><p>c</p>"
