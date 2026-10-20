"""Conversión entre el subconjunto de HTML de los párrafos (`<b> <i> <u> <a href> <br>`) y tramos de texto con estilo.

La interfaz convierte esos tramos en etiquetas de GtkTextBuffer y de vuelta (ver ui/richtext.py).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


@dataclass(frozen=True)
class Style:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    link: Optional[str] = None


@dataclass
class Run:
    text: str
    style: Style


# MARK: - Lectura

def parse(html: str) -> list[Run]:
    """Interpreta el HTML en tramos de texto con estilo. Las etiquetas desconocidas se ignoran
    (su texto se conserva); `<div>`/`<p>` y `<br>` se convierten en saltos de línea."""
    runs: list[Run] = []
    style = Style()
    stack: list[tuple[str, Style]] = []
    text: list[str] = []

    def flush():
        if not text:
            return
        decoded = decode_entities("".join(text))
        text.clear()
        if runs and runs[-1].style == style:
            runs[-1].text += decoded
        else:
            runs.append(Run(decoded, style))

    def newline():
        flush()
        if runs and runs[-1].style == style:
            runs[-1].text += "\n"
        else:
            runs.append(Run("\n", style))

    i, n = 0, len(html)
    while i < n:
        c = html[i]
        close = html.find(">", i) if c == "<" else -1
        if close < 0:
            # Los saltos de línea literales del HTML equivalen a espacios.
            text.append(" " if c in "\n\r" else c)
            i += 1
            continue
        raw = html[i + 1:close]
        i = close + 1
        closing = raw.startswith("/")
        body = raw[1:] if closing else raw
        parts = [p for p in _split_any(body, " /\t") if p]
        name = parts[0].lower() if parts else ""

        if name == "br":
            newline()
        elif name in ("div", "p"):
            # Un bloque separa líneas, salvo al principio o justo después de otro salto.
            at_line_start = not text and (runs[-1].text.endswith("\n") if runs else True)
            if not at_line_start:
                newline()
        elif name in ("b", "strong", "i", "em", "u", "a"):
            flush()
            if closing:
                idx = next((k for k in range(len(stack) - 1, -1, -1) if stack[k][0] == name), None)
                if idx is not None:
                    style = stack[idx][1]
                    del stack[idx:]
            else:
                stack.append((name, style))
                if name in ("b", "strong"):
                    style = replace(style, bold=True)
                elif name in ("i", "em"):
                    style = replace(style, italic=True)
                elif name == "u":
                    style = replace(style, underline=True)
                else:
                    href = attribute("href", body)
                    style = replace(style, link=decode_entities(href) if href is not None else None)
    flush()
    # Quita el salto final que deja un `</div>` de cierre.
    if runs and runs[-1].text.endswith("\n"):
        runs[-1].text = runs[-1].text[:-1]
        if not runs[-1].text:
            runs.pop()
    return runs


def _split_any(s: str, seps: str) -> list[str]:
    out, cur = [], []
    for ch in s:
        if ch in seps:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def plain_text(html: str) -> str:
    return "".join(r.text for r in parse(html)).replace("\n", " ").strip(" ")


# MARK: - Escritura

def html_from_runs(runs: list[Run]) -> str:
    out: list[str] = []
    open_style = Style()

    def close_all():
        nonlocal open_style
        if open_style.link is not None:
            out.append("</a>")
        if open_style.underline:
            out.append("</u>")
        if open_style.italic:
            out.append("</i>")
        if open_style.bold:
            out.append("</b>")
        open_style = Style()

    for run in runs:
        if not run.text:
            continue
        s = run.style
        if s != open_style:
            close_all()
            if s.bold:
                out.append("<b>")
            if s.italic:
                out.append("<i>")
            if s.underline:
                out.append("<u>")
            if s.link is not None:
                out.append(f'<a href="{escape(s.link)}">')
            open_style = s
        out.append(escape(run.text).replace("\n", "<br>"))
    close_all()
    return "".join(out)


# MARK: - Utilidades

def attribute(name: str, tag: str) -> Optional[str]:
    pos = tag.lower().find(name.lower() + "=")
    if pos < 0:
        return None
    rest = tag[pos + len(name) + 1:]
    if not rest:
        return None
    q = rest[0]
    if q in "\"'":
        end = rest.find(q, 1)
        return rest[1:end] if end >= 0 else None
    out = []
    for ch in rest:
        if ch.isspace() or ch == ">":
            break
        out.append(ch)
    return "".join(out)


def escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def decode_entities(s: str) -> str:
    if "&" not in s:
        return s
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "&":
            semi = s.find(";", i, i + 10)
            if semi >= 0:
                ch = _decode_entity(s[i + 1:semi])
                if ch is not None:
                    out.append(ch)
                    i = semi + 1
                    continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _decode_entity(e: str) -> Optional[str]:
    simple = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "#39": "'", "nbsp": " "}
    if e in simple:
        return simple[e]
    try:
        if e[:2] in ("#x", "#X"):
            return chr(int(e[2:], 16))
        if e.startswith("#"):
            return chr(int(e[1:]))
    except (ValueError, OverflowError):
        return None
    return None
