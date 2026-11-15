"""Reduced YAML reader for mfi-server automations (standard library only).

Reads the subset that Home Assistant automation files use: block mappings and
block lists indented with spaces, simple scalars, strings in single or double
quotes, inline lists of scalars and '#' comments. Anything outside the subset
raises YamlError with the 1-based line number.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

QUOTES = ("'", '"')
INT_RE = re.compile(r"[+-]?[0-9]+")
FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?")
DOUBLE_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "/": "/"}
UNSUPPORTED_START = {
    "&": "anchors are not supported",
    "*": "aliases are not supported",
    "!": "tags are not supported",
    "|": "block scalars are not supported",
    ">": "block scalars are not supported",
}


class YamlError(ValueError):
    """Text outside the reduced YAML subset; .line is the 1-based line of the error."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


def loads(text: str) -> object:
    """Read a reduced YAML document. An empty document gives None."""
    tokens = _tokenize(text)
    if not tokens:
        return None
    reader = _Reader(tokens)
    result = reader.block(tokens[0][1])
    if reader.pos != len(tokens):
        raise YamlError(tokens[reader.pos][0], "unexpected indentation or text")
    return result


def _unquoted_positions(text: str) -> Iterator[tuple[int, str]]:
    """Yield (index, char) for each character that is outside quoted strings."""
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and text[i + 1 : i + 2] == "'":
                    i += 2
                    continue
                quote = ""
        elif ch in QUOTES and (i == 0 or text[i - 1] in " \t[,"):
            quote = ch
        else:
            yield i, ch
        i += 1


def _comment_start(text: str) -> int:
    """Return the index of the '#' that starts a comment, or len(text)."""
    for i, ch in _unquoted_positions(text):
        if ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return i
    return len(text)


def _tokenize(text: str) -> list[list]:
    """Return [line, indent, content] for each line with content; blank and comment lines are dropped."""
    tokens = []
    for number, raw in enumerate(text.splitlines(), start=1):
        body = raw.lstrip(" \t")
        indent_text = raw[: len(raw) - len(body)]
        if "\t" in indent_text:
            raise YamlError(number, "tabs are not allowed for indentation")
        content = body[: _comment_start(body)].rstrip()
        if content == "":
            continue
        if content in ("---", "..."):
            raise YamlError(number, "document markers are not supported")
        tokens.append([number, len(indent_text), content])
    return tokens


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _key_split(text: str) -> int:
    """Return the index of the ':' that ends a mapping key, or -1 when the text is not a 'key: value' line."""
    if text[:1] in ("[", "{"):
        return -1
    for i, ch in _unquoted_positions(text):
        if ch == ":" and text[i + 1 : i + 2] in ("", " "):
            return i
    return -1


def _split_commas(body: str) -> list[str]:
    parts = []
    start = 0
    for i, ch in _unquoted_positions(body):
        if ch == ",":
            parts.append(body[start:i])
            start = i + 1
    parts.append(body[start:])
    return parts


def _check_start(text: str, line: int) -> None:
    message = UNSUPPORTED_START.get(text[:1])
    if message:
        raise YamlError(line, message)


def _quoted(text: str, line: int) -> str:
    """Return the value of a whole single- or double-quoted string."""
    quote = text[0]
    out: list[str] = []
    i = 1
    while i < len(text):
        ch = text[i]
        if quote == "'" and ch == "'" and text[i + 1 : i + 2] == "'":
            out.append("'")
            i += 2
            continue
        if ch == quote:
            if i != len(text) - 1:
                raise YamlError(line, "text after the closing quote")
            return "".join(out)
        if quote == '"' and ch == "\\":
            escaped = text[i + 1 : i + 2]
            if escaped not in DOUBLE_ESCAPES:
                raise YamlError(line, "unsupported escape in double-quoted string")
            out.append(DOUBLE_ESCAPES[escaped])
            i += 2
            continue
        out.append(ch)
        i += 1
    raise YamlError(line, "quoted string is not closed on this line")


def _inline_list(text: str, line: int) -> list:
    """Parse '[a, b]' where every item is a scalar."""
    if not text.endswith("]"):
        raise YamlError(line, "inline list is not closed on this line")
    body = text[1:-1].strip()
    if body == "":
        return []
    items = []
    for part in _split_commas(body):
        item = part.strip()
        if item == "" or item[0] in "[{":
            raise YamlError(line, "inline lists take scalars only")
        items.append(_scalar(item, line))
    return items


def _scalar(text: str, line: int) -> object:
    _check_start(text, line)
    if text[0] in QUOTES:
        return _quoted(text, line)
    if text[0] == "[":
        return _inline_list(text, line)
    if text[0] == "{":
        if text == "{}":
            return {}
        raise YamlError(line, "inline mappings are not supported")
    if text in ("null", "~"):
        return None
    if text in ("true", "false"):
        return text == "true"
    if INT_RE.fullmatch(text):
        return int(text)
    if FLOAT_RE.fullmatch(text) and any(c in text for c in ".eE"):
        return float(text)
    return text


def _key(text: str, line: int) -> str:
    if text == "":
        raise YamlError(line, "empty key")
    _check_start(text, line)
    if text[0] in QUOTES:
        return _quoted(text, line)
    return text


class _Reader:
    """Walks the tokens of one document; each token is [line, indent, content]."""

    def __init__(self, tokens: list[list]) -> None:
        self.tokens = tokens
        self.pos = 0

    def block(self, indent: int) -> object:
        """Read the block that starts at the current token, indented by indent."""
        line, _, text = self.tokens[self.pos]
        if _is_item(text):
            return self.sequence(indent)
        if _key_split(text) >= 0:
            return self.mapping(indent)
        self.pos += 1
        return _scalar(text, line)

    def mapping(self, indent: int) -> dict:
        result: dict = {}
        while self.pos < len(self.tokens):
            line, column, text = self.tokens[self.pos]
            if column < indent:
                break
            if column > indent:
                raise YamlError(line, "unexpected indentation")
            if _is_item(text):
                raise YamlError(line, "list item where a mapping key is expected")
            cut = _key_split(text)
            if cut < 0:
                raise YamlError(line, "expected 'key: value'")
            key = _key(text[:cut].rstrip(), line)
            if key in result:
                raise YamlError(line, f"duplicate key '{key}'")
            value = text[cut + 1 :].strip()
            self.pos += 1
            if value:
                result[key] = _scalar(value, line)
            else:
                result[key] = self.value_after(indent, same_level_list=True)
        return result

    def sequence(self, indent: int) -> list:
        items: list = []
        while self.pos < len(self.tokens):
            line, column, text = self.tokens[self.pos]
            if column < indent:
                break
            if column > indent:
                raise YamlError(line, "unexpected indentation")
            if not _is_item(text):
                break
            rest = text[1:].lstrip(" \t")
            if rest == "":
                self.pos += 1
                items.append(self.value_after(indent, same_level_list=False))
            else:
                # The text after '- ' is a block in its own column, so a mapping can continue below it.
                item_column = column + len(text) - len(rest)
                self.tokens[self.pos] = [line, item_column, rest]
                items.append(self.block(item_column))
        return items

    def value_after(self, indent: int, same_level_list: bool) -> object:
        """Value of an empty 'key:' or '-' line: the block indented below it, or None."""
        if self.pos >= len(self.tokens):
            return None
        _, column, text = self.tokens[self.pos]
        if column > indent or (same_level_list and column == indent and _is_item(text)):
            return self.block(column)
        return None
