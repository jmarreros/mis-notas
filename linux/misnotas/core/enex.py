"""Importación de archivos .enex exportados de Evernote."""
from __future__ import annotations

import calendar
import time
import xml.sax
import xml.sax.handler
from dataclasses import dataclass
from typing import Optional

from . import inline_html
from .models import Block, TodoItem


@dataclass
class EnexNote:
    title: str
    created: Optional[int]
    updated: Optional[int]
    blocks: list[Block]


class _Handler(xml.sax.handler.ContentHandler):
    """Solo conserva texto: los recursos (imágenes y adjuntos) se descartan."""

    def __init__(self):
        super().__init__()
        self.notes: list[EnexNote] = []
        self.current: Optional[dict] = None
        self.element = ""
        self.buffer: list[str] = []
        self.depth_in_resource = 0

    def startElement(self, name, attrs):
        if name == "resource":
            self.depth_in_resource += 1
        if self.depth_in_resource:
            return
        if name == "note":
            self.current = {"title": "", "created": "", "updated": "", "content": ""}
        self.element = name
        self.buffer = []

    def characters(self, content):
        if self.depth_in_resource == 0 and self.current is not None:
            self.buffer.append(content)

    def endElement(self, name):
        if name == "resource":
            self.depth_in_resource -= 1
            return
        if self.depth_in_resource or self.current is None:
            return
        raw = "".join(self.buffer)
        text = raw.strip()
        if name == "title" and self.element == "title":
            self.current["title"] = text
        elif name in ("created", "updated"):
            self.current[name] = text
        elif name == "content":
            self.current["content"] = raw
        elif name == "note":
            c = self.current
            self.notes.append(EnexNote(c["title"], parse_date(c["created"]), parse_date(c["updated"]),
                                       enml_to_blocks(c["content"])))
            self.current = None
        self.buffer = []


def _parser(handler) -> xml.sax.xmlreader.XMLReader:
    p = xml.sax.make_parser()
    p.setFeature(xml.sax.handler.feature_external_ges, False)
    p.setFeature(xml.sax.handler.feature_external_pes, False)
    p.setFeature(xml.sax.handler.feature_namespaces, False)
    p.setContentHandler(handler)
    return p


def parse_file(path: str) -> list[EnexNote]:
    h = _Handler()
    with open(path, "rb") as f:
        _parser(h).parse(f)
    return h.notes


def parse_bytes(data: bytes) -> list[EnexNote]:
    import io
    h = _Handler()
    _parser(h).parse(io.BytesIO(data))
    return h.notes


def parse_date(s: str) -> Optional[int]:
    if not s:
        return None
    try:
        t = time.strptime(s, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None
    return calendar.timegm(t) * 1000


# MARK: - ENML → bloques

_BLOCK_TAGS = {"div", "p", "blockquote", "tr", "table", "ul", "ol", "en-note", "section", "article", "center",
               "dl", "dt", "dd", "hr"}


def _inline_tag(name: str) -> str:
    return {"strong": "b", "em": "i"}.get(name, name)


class _ENMLConverter:
    """Convierte ENML (el XHTML de Evernote) en bloques: líneas consecutivas → un párrafo,
    `en-todo` y listas de tareas → bloque de tareas, `h1…h6` → encabezado,
    bloques de código y `<pre>` → código. Negrita, cursiva, subrayado y enlaces se conservan."""

    def __init__(self):
        self.blocks: list[Block] = []
        self.para = ""
        self.at_line_start = True
        self.todo_items: list[TodoItem] = []
        self.current_todo: Optional[TodoItem] = None
        self.mode = "normal"          # normal, heading, code, skip
        self.preserve_spaces = False  # en modo code
        self.mode_tag = ""
        self.mode_depth = 0
        self.buffer = ""
        self.lists: list[list] = []   # [todo, ordered, counter]
        self.cell_index = 0

    def handle(self, tok):
        kind = tok[0]
        if self.mode == "skip":
            if kind == "open" and tok[1] == self.mode_tag and not tok[3]:
                self.mode_depth += 1
            if kind == "close" and tok[1] == self.mode_tag:
                self.mode_depth -= 1
                if self.mode_depth == 0:
                    self.mode = "normal"
            return
        if self.mode == "heading":
            if kind == "text":
                self.buffer += tok[1]
            elif kind == "close" and tok[1] == self.mode_tag:
                text = collapsing_whitespace(self.buffer).strip(" ")
                if text:
                    self.blocks.append(Block.heading(inline_html.escape(text)))
                self.mode = "normal"
                self.at_line_start = True
            return
        if self.mode == "code":
            if kind == "text":
                self.buffer += tok[1] if self.preserve_spaces else tok[1].replace("\n", "")
            elif kind == "open":
                name, self_closing = tok[1], tok[3]
                if name == "br":
                    self.buffer += "\n"
                elif name in _BLOCK_TAGS or name == "pre":
                    if self.buffer and not self.buffer.endswith("\n"):
                        self.buffer += "\n"
                    if name == self.mode_tag and not self_closing:
                        self.mode_depth += 1
            else:
                name = tok[1]
                if name == self.mode_tag:
                    self.mode_depth -= 1
                    if self.mode_depth == 0:
                        text = self.buffer.strip("\n")
                        if text:
                            self.blocks.append(Block.code(text))
                        self.mode = "normal"
                        self.at_line_start = True
                        return
                if name in _BLOCK_TAGS and self.buffer and not self.buffer.endswith("\n"):
                    self.buffer += "\n"
            return

        if kind == "text":
            self.append_text(tok[1])
        elif kind == "open":
            _, name, attrs, self_closing = tok
            style = attrs.get("style", "")
            if name == "br":
                self.hard_break()
            elif name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.flush_todo(); self.flush_paragraph()
                self.mode, self.mode_tag, self.buffer = "heading", name, ""
            elif name == "pre":
                self.flush_todo(); self.flush_paragraph()
                self.mode, self.preserve_spaces, self.mode_tag, self.mode_depth, self.buffer = "code", True, name, 1, ""
            elif name == "div" and "-en-codeblock" in style:
                self.flush_todo(); self.flush_paragraph()
                self.mode, self.preserve_spaces, self.mode_tag = "code", False, name
                self.mode_depth = 0 if self_closing else 1
                self.buffer = ""
            elif name in ("en-crypt", "style", "script", "title", "head"):
                if not self_closing:
                    self.mode, self.mode_tag, self.mode_depth = "skip", name, 1
            elif name == "en-todo":
                self.soft_break()
                self.flush_paragraph()
                self.current_todo = TodoItem("", attrs.get("checked") == "true")
            elif name in ("ul", "ol"):
                self.soft_break()
                self.lists.append(["--en-todo:true" in style, name == "ol", 0])
            elif name == "li":
                self.soft_break()
                if self.lists:
                    top = self.lists[-1]
                    if top[0]:
                        self.flush_paragraph()
                        self.current_todo = TodoItem("", "--en-checked:true" in style)
                    else:
                        top[2] += 1
                        indent = "    " * (len(self.lists) - 1)
                        marker = f"{top[2]}. " if top[1] else "• "
                        # El marcador no cuenta como contenido: el <div> interior no debe saltar de línea.
                        self.flush_todo()
                        self.para += inline_html.escape(indent + marker)
            elif name == "hr":
                self.flush_todo(); self.flush_paragraph()
                self.blocks.append(Block.divider())
            elif name in ("td", "th"):
                if self.cell_index > 0:
                    self.append_text(" | ")
                self.cell_index += 1
            elif name == "tr":
                self.soft_break()
                self.cell_index = 0
            elif name in ("b", "strong", "i", "em", "u"):
                if self.current_todo is None:
                    self.append_raw(f"<{_inline_tag(name)}>")
            elif name == "a":
                href = attrs.get("href")
                if self.current_todo is None and href:
                    self.append_raw(f'<a href="{inline_html.escape(href)}">')
            elif name in _BLOCK_TAGS:
                self.soft_break()
        else:
            name = tok[1]
            if name in ("ul", "ol"):
                self.soft_break()
                if self.lists:
                    self.lists.pop()
            elif name == "li":
                self.soft_break()
            elif name in ("b", "strong", "i", "em", "u"):
                if self.current_todo is None:
                    self.append_raw(f"</{_inline_tag(name)}>")
            elif name == "a":
                if self.current_todo is None:
                    self.append_raw("</a>")
            elif name in _BLOCK_TAGS:
                self.soft_break()

    def append_text(self, raw: str):
        t = collapsing_whitespace(raw)
        if self.at_line_start:
            t = t.lstrip(" ")
        if not t:
            return
        if self.current_todo is not None:
            self.current_todo.t += t
        else:
            self.flush_todo()
            self.para += inline_html.escape(t)
        self.at_line_start = False

    def append_raw(self, html: str):
        self.flush_todo()
        self.para += html
        if not html.startswith("<"):
            self.at_line_start = False

    def soft_break(self):
        """Fin de un elemento de bloque: salta de línea si no se está ya al principio de una."""
        if self.current_todo is not None:
            # Una tarea aún sin texto sigue abierta (p. ej. el <div> dentro de un <li> de tareas).
            if not self.current_todo.t.strip(" "):
                return
            self.current_todo.t = self.current_todo.t.strip(" ")
            self.todo_items.append(self.current_todo)
            self.current_todo = None
            self.at_line_start = True
            return
        if self.at_line_start:
            return
        self.para += "<br>"
        self.at_line_start = True

    def hard_break(self):
        if self.current_todo is not None:
            self.soft_break()
            return
        if self.para:
            self.para += "<br>"
        self.at_line_start = True

    def flush_todo(self):
        if self.current_todo is not None:
            self.soft_break()
        if not self.todo_items:
            return
        self.flush_paragraph()
        self.blocks.append(Block.todo(self.todo_items))
        self.todo_items = []

    def flush_paragraph(self):
        html = self.para
        while html.endswith("<br>"):
            html = html[:-4]
        while html.startswith("<br>"):
            html = html[4:]
        self.para = ""
        self.at_line_start = True
        if not inline_html.plain_text(html).strip(" "):
            return
        # Las tareas pendientes van antes que este párrafo.
        if self.todo_items:
            self.blocks.append(Block.todo(self.todo_items))
            self.todo_items = []
        self.blocks.append(Block.paragraph(html))


def enml_to_blocks(enml: str) -> list[Block]:
    c = _ENMLConverter()
    for tok in tokenize(enml):
        c.handle(tok)
    c.flush_todo()
    c.flush_paragraph()
    return c.blocks or [Block.paragraph()]


# MARK: - Tokenizador

def tokenize(s: str) -> list[tuple]:
    """Tokenizador tolerante de HTML/XHTML. Tokens: ("open", name, attrs, self_closing), ("close", name), ("text", t)."""
    out: list[tuple] = []
    text: list[str] = []
    i, n = 0, len(s)

    def flush():
        if text:
            out.append(("text", inline_html.decode_entities("".join(text))))
            text.clear()

    while i < n:
        if s[i] != "<":
            text.append(s[i])
            i += 1
            continue
        if s.startswith("<!--", i):
            flush()
            end = s.find("-->", i)
            i = n if end < 0 else end + 3
            continue
        if s.startswith("<![CDATA[", i):
            flush()
            start = i + 9
            end = s.find("]]>", start)
            out.append(("text", s[start:end if end >= 0 else n]))
            i = n if end < 0 else end + 3
            continue
        close = s.find(">", i)
        if close < 0:
            text.append(s[i:])
            break
        inner = s[i + 1:close]
        i = close + 1
        if inner.startswith("!") or inner.startswith("?"):  # DOCTYPE, <?xml ?>
            continue
        flush()
        if inner.startswith("/"):
            out.append(("close", inner[1:].strip().lower()))
            continue
        self_closing = inner.endswith("/")
        body = inner[:-1] if self_closing else inner
        k = 0
        while k < len(body) and not body[k].isspace() and body[k] != "/":
            k += 1
        name = body[:k].lower()
        if not name:
            continue
        out.append(("open", name, _attributes(body[k:]), self_closing))
    flush()
    return out


def _attributes(s: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    i, n = 0, len(s)

    def skip(i):
        while i < n and s[i].isspace():
            i += 1
        return i

    while i < n:
        i = skip(i)
        start = i
        while i < n and not s[i].isspace() and s[i] != "=":
            i += 1
        name = s[start:i].lower()
        i = skip(i)
        if i >= n or s[i] != "=":
            if name:
                attrs[name] = ""
            continue
        i = skip(i + 1)
        if i >= n:
            break
        q = s[i]
        if q in "\"'":
            i += 1
            start = i
            while i < n and s[i] != q:
                i += 1
            value = s[start:i]
            if i < n:
                i += 1
        else:
            start = i
            while i < n and not s[i].isspace():
                i += 1
            value = s[start:i]
        if name:
            attrs[name] = inline_html.decode_entities(value)
    return attrs


def collapsing_whitespace(s: str) -> str:
    """Espacios en blanco consecutivos (incluidos saltos de línea) → un espacio, como en HTML."""
    out: list[str] = []
    last_space = False
    for ch in s:
        if ch in " \n\t\r":
            if not last_space:
                out.append(" ")
            last_space = True
        else:
            out.append(" " if ch == " " else ch)
            last_space = False
    return "".join(out)
