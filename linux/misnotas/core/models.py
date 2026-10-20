"""Modelos compartidos con la API: notas, libretas, bloques y adjuntos.

El JSON es el mismo que guarda la API Laravel (snake_case). Las fechas son milisegundos desde epoch.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from . import inline_html


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class TodoItem:
    t: str = ""
    done: bool = False

    def to_json(self) -> dict:
        return {"t": self.t, "done": self.done}

    @staticmethod
    def from_json(d: dict) -> "TodoItem":
        # Tolerante: registros antiguos del servidor guardaron las cadenas vacías como null.
        return TodoItem(t=d.get("t") or "", done=bool(d.get("done") or False))


# Tipos de bloque.
P, H, TODO, CODE, LINK, IMG, HR = "p", "h", "todo", "code", "link", "img", "hr"

# Campos opcionales del bloque: nombre en Python → clave JSON.
_BLOCK_FIELDS = [("html", "html"), ("items", "items"), ("lang", "lang"), ("text", "text"), ("title", "title"),
                 ("url", "url"), ("attachment_id", "attachment_id"), ("caption", "caption"), ("width", "width")]


@dataclass
class Block:
    """Un bloque de contenido. Estructura plana con campos opcionales según el tipo, idéntica al JSON de la API."""
    type: str
    id: str = field(default_factory=new_id)
    html: Optional[str] = None            # p, h
    items: Optional[list[TodoItem]] = None  # todo
    lang: Optional[str] = None            # code
    text: Optional[str] = None            # code
    title: Optional[str] = None           # link
    url: Optional[str] = None             # link
    attachment_id: Optional[str] = None   # img
    caption: Optional[str] = None         # img
    width: Optional[float] = None         # img: ancho en píxeles (None = ajustado al editor)

    @staticmethod
    def paragraph(html: str = "") -> "Block":
        return Block(type=P, html=html)

    @staticmethod
    def heading(html: str = "") -> "Block":
        return Block(type=H, html=html)

    @staticmethod
    def todo(items: Optional[list[TodoItem]] = None) -> "Block":
        return Block(type=TODO, items=items if items is not None else [TodoItem("")])

    @staticmethod
    def code(text: str = "", lang: str = "CÓDIGO") -> "Block":
        return Block(type=CODE, lang=lang, text=text)

    @staticmethod
    def link(url: str = "", title: str = "Nuevo enlace") -> "Block":
        return Block(type=LINK, title=title, url=url)

    @staticmethod
    def divider() -> "Block":
        return Block(type=HR)

    @staticmethod
    def image(attachment_id: str, caption: str = "") -> "Block":
        return Block(type=IMG, attachment_id=attachment_id, caption=caption)

    @property
    def is_text(self) -> bool:
        return self.type in (P, H)

    @property
    def plain_text(self) -> str:
        if self.type in (P, H):
            return inline_html.plain_text(self.html or "")
        if self.type == TODO:
            return " ".join(i.t for i in self.items or [])
        if self.type == CODE:
            return self.text or ""
        if self.type == LINK:
            return " ".join(x for x in (self.title, self.url) if x is not None)
        if self.type == IMG:
            return self.caption or ""
        return ""

    def copy(self, **changes) -> "Block":
        b = replace(self, **changes)
        if b.items is not None and "items" not in changes:
            b.items = [replace(i) for i in b.items]
        return b

    def to_json(self) -> dict:
        d: dict[str, Any] = {"id": self.id, "type": self.type}
        for attr, key in _BLOCK_FIELDS:
            v = getattr(self, attr)
            if v is None:
                continue
            d[key] = [i.to_json() for i in v] if attr == "items" else v
        return d

    @staticmethod
    def from_json(d: dict) -> "Block":
        b = Block(type=d.get("type") or P, id=d.get("id") or new_id())
        for attr, key in _BLOCK_FIELDS:
            v = d.get(key, d.get(_camel(key)))
            if v is None:
                continue
            if attr == "items":
                v = [TodoItem.from_json(i) for i in v if isinstance(i, dict)]
            elif attr == "width":
                v = float(v)
            setattr(b, attr, v)
        return b


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(w.capitalize() for w in rest)


@dataclass
class Notebook:
    name: str
    id: str = field(default_factory=new_id)
    sort: int = 0
    created_at: int = field(default_factory=now_ms)
    updated_at: int = field(default_factory=now_ms)
    deleted_at: Optional[int] = None
    # Cambio local pendiente de enviar al servidor.
    dirty: bool = True

    def to_json(self) -> dict:
        d = {"id": self.id, "name": self.name, "sort": self.sort, "created_at": self.created_at,
             "updated_at": self.updated_at, "dirty": self.dirty}
        if self.deleted_at is not None:
            d["deleted_at"] = self.deleted_at
        return d

    @staticmethod
    def from_json(d: dict) -> "Notebook":
        # Los registros que llegan del servidor no traen `dirty`.
        return Notebook(id=d["id"], name=d.get("name") or "", sort=int(d.get("sort") or 0),
                        created_at=int(d["created_at"]), updated_at=int(d["updated_at"]),
                        deleted_at=_opt_int(d.get("deleted_at")), dirty=bool(d.get("dirty") or False))


@dataclass
class Note:
    notebook_id: Optional[str]
    id: str = field(default_factory=new_id)
    title: str = ""
    blocks: list[Block] = field(default_factory=lambda: [Block.paragraph()])
    created_at: int = field(default_factory=now_ms)
    updated_at: int = field(default_factory=now_ms)
    trashed_at: Optional[int] = None
    deleted_at: Optional[int] = None
    favorite: bool = False
    dirty: bool = True

    @property
    def is_trashed(self) -> bool:
        return self.trashed_at is not None

    @property
    def body_text(self) -> str:
        """Texto plano del contenido (sin título), para búsqueda, extractos y recuento de palabras."""
        return " ".join(t for t in (b.plain_text for b in self.blocks) if t)

    @property
    def word_count(self) -> int:
        return len((self.title + " " + self.body_text).split())

    @property
    def has_image(self) -> bool:
        return any(b.type == IMG for b in self.blocks)

    def copy(self, **changes) -> "Note":
        n = replace(self, **changes)
        if "blocks" not in changes:
            n.blocks = [b.copy() for b in self.blocks]
        return n

    def to_json(self) -> dict:
        d = {"id": self.id, "title": self.title, "blocks": [b.to_json() for b in self.blocks],
             "created_at": self.created_at, "updated_at": self.updated_at, "favorite": self.favorite, "dirty": self.dirty}
        for key in ("notebook_id", "trashed_at", "deleted_at"):
            v = getattr(self, key)
            if v is not None:
                d[key] = v
        return d

    @staticmethod
    def from_json(d: dict) -> "Note":
        return Note(id=d["id"], notebook_id=d.get("notebook_id"), title=d.get("title") or "",
                    blocks=[Block.from_json(b) for b in d.get("blocks") or [] if isinstance(b, dict)],
                    created_at=int(d["created_at"]), updated_at=int(d["updated_at"]),
                    trashed_at=_opt_int(d.get("trashed_at")), deleted_at=_opt_int(d.get("deleted_at")),
                    favorite=bool(d.get("favorite") or False), dirty=bool(d.get("dirty") or False))


@dataclass
class Attachment:
    """Imagen local de una nota. El archivo vive en el directorio de adjuntos con nombre `<id>.<ext>`."""
    id: str
    note_id: Optional[str]
    file_name: str
    mime: str
    # Ya se subió al servidor.
    uploaded: bool


def _opt_int(v) -> Optional[int]:
    return None if v is None else int(v)
