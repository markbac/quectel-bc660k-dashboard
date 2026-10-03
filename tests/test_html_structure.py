"""The page's tags must balance, or rows nest inside one another (#95)."""
from html.parser import HTMLParser
from pathlib import Path

VOID = {"meta", "link", "input", "br", "img", "hr", "source", "area", "base", "col", "embed", "wbr"}
INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"


class _Balance(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"</{tag}> on line {self.getpos()[0]} does not match {self.stack[-1:]}")


def test_index_html_tags_are_balanced():
    parser = _Balance()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    assert parser.errors == []
    assert parser.stack == []
