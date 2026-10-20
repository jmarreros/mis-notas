"""Estado de la interfaz. Copia en memoria de la réplica local: toda edición se escribe en SQLite
al momento y se refleja aquí. Las vistas se suscriben a «temas» y se refrescan en bloque."""
from __future__ import annotations

import mimetypes
import os
import shutil
from dataclasses import dataclass
from typing import Callable, Optional

from .core import inline_html
from .core.database import NotesRepository
from .core.models import CODE, HR, IMG, LINK, P, TODO, Attachment, Block, Note, Notebook, new_id, now_ms
from .core.text import contains, fold

# Navegación: ("all",), ("favorites",), ("recents",), ("trash",), ("notebook", id)
ALL, FAVORITES, RECENTS, TRASH = ("all",), ("favorites",), ("recents",), ("trash",)


def notebook_nav(id: str) -> tuple:
    return ("notebook", id)


@dataclass
class FocusTarget:
    """Qué control debe recibir el foco (título, un bloque, una tarea…)."""
    note_id: str
    key: str
    # Cursor al principio en vez de al final (al bajar con ↓ desde el bloque anterior).
    at_start: bool = False

    def same(self, other: Optional["FocusTarget"]) -> bool:
        return other is not None and other.note_id == self.note_id and other.key == self.key


class AppState:
    RECENT_LIMIT = 20

    def __init__(self, repo: NotesRepository, attachments_dir: str):
        self.repo = repo
        self.attachments_dir = attachments_dir

        self.notebooks: list[Notebook] = []
        # Notas vivas (también las de la Papelera), más recientes primero.
        self.notes: list[Note] = []

        self.nav: tuple = ALL
        self._selected_id: Optional[str] = None
        # Últimas notas vistas, la más reciente primero. Solo locales.
        self.recent_ids: list[str] = []
        # Notas marcadas en la lista (Ctrl+clic, Mayús+clic, Ctrl+A). Vacío = solo `selected_id`.
        self.multi_selection: set[str] = set()
        self._query = ""
        self.scope = "all"  # "all" | "current"
        self.sidebar_open = True
        self.focus: Optional[FocusTarget] = None
        # Último bloque con el foco: los bloques nuevos se insertan detrás de él.
        self.active_block_id: Optional[str] = None
        # Nota con todos sus bloques seleccionados (Ctrl+A con el bloque actual ya seleccionado entero).
        self.all_selected_note_id: Optional[str] = None
        # Cambia cuando se descarga una imagen, para refrescar las vistas que la muestran.
        self.attachments_version = 0
        self.search_matches: set[str] = set()

        # Se llama tras cada cambio local (la sincronización programa un envío).
        self.on_local_change: Callable[[], None] = lambda: None
        # Muestra un error al usuario.
        self.on_error: Callable[[str], None] = lambda msg: None
        # La interfaz parte el texto con el foco por el cursor: devuelve (html antes, html después) o None.
        self.split_active_text: Callable[[], Optional[tuple[str, str]]] = lambda: None
        # Programa una llamada en el bucle principal (GLib.idle_add en la app).
        self.schedule: Callable[[Callable], None] = lambda fn: fn()

        self._subscribers: list[Callable[[set], None]] = []
        self._pending: set = set()
        self._undo: list[tuple[str, list[Block], str]] = []
        self._redo: list[tuple[str, list[Block], str]] = []
        self._skip_recent = False

        self.reload()
        self._selected_id = self.list[0].id if self.list else None
        # Después de seleccionar: la nota que se abre sola al iniciar no cuenta como vista.
        self._perform(lambda: setattr(self, "recent_ids", repo.recent_ids()))

    # MARK: Avisos

    def subscribe(self, fn: Callable[[set], None]):
        self._subscribers.append(fn)

    def changed(self, *topics: str):
        first = not self._pending
        self._pending.update(topics)
        if first:
            self.schedule(self._flush)

    def _flush(self):
        topics, self._pending = self._pending, set()
        for fn in list(self._subscribers):
            fn(topics)
        return False

    def _perform(self, body: Callable[[], None]):
        try:
            body()
        except Exception as e:  # noqa: BLE001 — se muestra al usuario, como en macOS
            self.on_error(str(e))

    # MARK: Propiedades con efectos

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    @selected_id.setter
    def selected_id(self, value: Optional[str]):
        if value == self._selected_id:
            return
        self._selected_id = value
        self._note_viewed(value)
        self.changed("selection")

    @property
    def query(self) -> str:
        return self._query

    @query.setter
    def query(self, value: str):
        if value == self._query:
            return
        self._query = value
        self._update_search()
        self.changed("query", "list")

    def set_scope(self, scope: str):
        self.scope = scope
        self.changed("query", "list")

    def set_sidebar_open(self, open: bool):
        self.sidebar_open = open
        self.changed("sidebar")

    def set_focus(self, target: Optional[FocusTarget]):
        self.focus = target
        if target is not None:
            self.changed("focus")

    def _note_viewed(self, id: Optional[str]):
        if self._skip_recent or id is None or not any(n.id == id and not n.is_trashed for n in self.notes):
            return
        # Dentro de Recientes la lista no se reordena bajo el cursor al hacer clic.
        if self.nav == RECENTS and id in self.recent_ids:
            return
        self.recent_ids = [id] + [x for x in self.recent_ids if x != id]
        del self.recent_ids[self.RECENT_LIMIT:]
        self._perform(lambda: self.repo.set_recent_ids(self.recent_ids))
        self.changed("counts")

    def reload(self):
        def body():
            self.notebooks = self.repo.notebooks()
            self.notes = self.repo.notes()
        self._perform(body)
        self._update_search()
        if self._selected_id and not any(n.id == self._selected_id for n in self.notes):
            self.selected_id = self.list[0].id if self.list else None
        self.changed("notes", "notebooks", "list", "counts", "editor")

    # MARK: Consultas

    @property
    def trimmed_query(self) -> str:
        return self._query.strip()

    @property
    def is_searching(self) -> bool:
        return bool(self.trimmed_query)

    @property
    def live_notes(self) -> list[Note]:
        return [n for n in self.notes if not n.is_trashed]

    @property
    def favorite_count(self) -> int:
        return sum(1 for n in self.notes if n.favorite and not n.is_trashed)

    @property
    def recent_notes(self) -> list[Note]:
        by_id = {n.id: n for n in self.notes}
        return [by_id[i] for i in self.recent_ids if i in by_id and not by_id[i].is_trashed]

    @property
    def trash_count(self) -> int:
        return sum(1 for n in self.notes if n.is_trashed)

    @property
    def selected_note(self) -> Optional[Note]:
        return self.note(self._selected_id)

    def note(self, id: Optional[str]) -> Optional[Note]:
        if id is None:
            return None
        return next((n for n in self.notes if n.id == id), None)

    def notebook_name(self, id: Optional[str]) -> str:
        if id is None:
            return ""
        return next((nb.name for nb in self.notebooks if nb.id == id), "")

    def count_in(self, notebook: Notebook) -> int:
        return sum(1 for n in self.notes if n.notebook_id == notebook.id and not n.is_trashed)

    def matches(self, note: Note, nav: tuple) -> bool:
        if nav == TRASH:
            return note.is_trashed
        if note.is_trashed:
            return False
        if nav[0] == "notebook":
            return note.notebook_id == nav[1]
        if nav == FAVORITES:
            return note.favorite
        if nav == RECENTS:
            return note.id in self.recent_ids
        return True

    @property
    def list(self) -> list[Note]:
        """Notas de la columna central según la navegación y la búsqueda."""
        q = self.trimmed_query
        if not q:
            return self.recent_notes if self.nav == RECENTS else [n for n in self.notes if self.matches(n, self.nav)]
        base = self.live_notes if self.scope == "all" else [n for n in self.notes if self.matches(n, self.nav)]
        found = [n for n in base if n.id in self.search_matches or contains(self.notebook_name(n.notebook_id), q)]
        # Primero las que coinciden por el título; después, las de contenido. Cada grupo conserva su orden.
        terms = [fold(t) for t in q.split()]

        def in_title(n: Note) -> bool:
            t = fold(n.title)
            return all(term in t for term in terms)

        return [n for n in found if in_title(n)] + [n for n in found if not in_title(n)]

    def nav_label(self, nav: tuple) -> str:
        if nav[0] == "notebook":
            return self.notebook_name(nav[1])
        return {"all": "Todas las notas", "favorites": "Favoritas", "recents": "Recientes", "trash": "Papelera"}[nav[0]]

    def _update_search(self):
        q = self.trimmed_query
        if not q:
            self.search_matches = set()
            return
        self._perform(lambda: setattr(self, "search_matches", self.repo.search(q)))
        lst = self.list
        if self._selected_id and any(n.id == self._selected_id for n in lst):
            return
        self.selected_id = lst[0].id if lst else None

    # MARK: Navegación

    def select_nav(self, nav: tuple):
        self.nav = nav
        self._query = ""
        self.search_matches = set()
        self.multi_selection = set()
        # Cambiar de vista autoselecciona la primera nota: no cuenta como vista.
        self._skip_recent = True
        lst = self.list
        self.selected_id = lst[0].id if lst else None
        self._skip_recent = False
        self.changed("nav", "query", "list", "counts")

    def select_note(self, id: str):
        self.multi_selection = set()
        self.selected_id = id
        self.active_block_id = None
        self.changed("marks")

    # MARK: Selección múltiple

    def is_marked(self, id: str) -> bool:
        return id in self.multi_selection

    def toggle_mark(self, id: str):
        if not self.multi_selection and self._selected_id:
            self.multi_selection = {self._selected_id}
        self.multi_selection ^= {id}
        self.selected_id = id
        self.active_block_id = None
        if len(self.multi_selection) <= 1:
            self.multi_selection = set()
        self.changed("marks")

    def extend_mark(self, id: str):
        ids = [n.id for n in self.list]
        if id not in ids:
            return
        to = ids.index(id)
        frm = ids.index(self._selected_id) if self._selected_id in ids else to
        self.multi_selection = set(ids[min(frm, to):max(frm, to) + 1])
        if len(self.multi_selection) <= 1:
            self.multi_selection = set()
        self.changed("marks")

    def mark_all(self):
        ids = [n.id for n in self.list]
        self.multi_selection = set(ids) if len(ids) > 1 else set()
        if self._selected_id is None and ids:
            self.selected_id = ids[0]
        self.changed("marks")

    def drag_payload(self, id: str) -> str:
        """Ids que viajan al arrastrar `id`: todas las marcadas si forma parte de ellas."""
        if id not in self.multi_selection:
            return id
        return "\n".join(n.id for n in self.list if n.id in self.multi_selection)

    def move_many(self, ids: list[str], notebook_id: str):
        for id in ids:
            self.move(id, notebook_id)
        self.multi_selection = set()
        self.changed("marks")

    # MARK: Notas

    def update(self, id: str, change: Callable[[Note], None]):
        """Aplica un cambio a una nota y lo guarda."""
        i = next((k for k, n in enumerate(self.notes) if n.id == id), None)
        if i is None:
            return
        n = self.notes[i].copy()
        change(n)
        if n == self.notes[i]:
            return

        def body():
            saved = self.repo.save_note(n)
            self.notes.pop(i)
            if saved.deleted_at is None:
                self.notes.insert(0, saved)
        self._perform(body)
        self.changed("notes", "list", "counts", "editor")
        self.on_local_change()

    def update_block(self, note_id: str, block_id: str, change: Callable[[Block], None]):
        def apply(n: Note):
            for b in n.blocks:
                if b.id == block_id:
                    change(b)
                    return
        self.update(note_id, apply)

    def new_note(self):
        def body():
            if self.nav[0] == "notebook":
                notebook_id = self.nav[1]
            elif self.notebooks:
                notebook_id = self.notebooks[0].id
            else:
                nb = self.repo.save_notebook(Notebook(name="Personal"))
                self.notebooks = [nb]
                notebook_id = nb.id
            note = self.repo.save_note(Note(notebook_id=notebook_id))
            self.notes.insert(0, note)
            if self.nav == TRASH:
                self.nav = ALL
            self._query = ""
            self.search_matches = set()
            self.selected_id = note.id
            self.set_focus(FocusTarget(note.id, "title"))
        self._perform(body)
        self.changed("notes", "notebooks", "nav", "query", "list", "counts", "editor")
        self.on_local_change()

    def _selection_after_removing(self, id: str) -> Optional[str]:
        lst = self.list
        i = next((k for k, n in enumerate(lst) if n.id == id), None)
        if i is None:
            return self._selected_id
        if i + 1 < len(lst):
            return lst[i + 1].id
        return lst[i - 1].id if i > 0 else None

    def trash(self, id: str):
        nxt = self._selection_after_removing(id)
        self.update(id, lambda n: setattr(n, "trashed_at", now_ms()))
        self.selected_id = nxt

    def toggle_favorite(self, id: str):
        note = self.note(id)
        if note is None or note.is_trashed:
            return
        # En la vista Favoritas, quitar la marca saca la nota de la lista: selecciona otra.
        nxt = self._selection_after_removing(id) if self.nav == FAVORITES and note.favorite else id
        self.update(id, lambda n: setattr(n, "favorite", not n.favorite))
        self.selected_id = nxt

    def restore(self, id: str):
        nxt = self._selection_after_removing(id)

        def change(n: Note):
            n.trashed_at = None
            # Si su libreta ya no existe, va a la primera.
            if not any(nb.id == n.notebook_id for nb in self.notebooks):
                n.notebook_id = self.notebooks[0].id if self.notebooks else None
        self.update(id, change)
        self.selected_id = nxt

    def delete_forever(self, id: str):
        note = self.note(id)
        if note is None:
            return
        nxt = self._selection_after_removing(id)

        def body():
            self.repo.delete_forever(note)
            self.notes = [n for n in self.notes if n.id != id]
        self._perform(body)
        self.selected_id = nxt
        self.changed("notes", "list", "counts", "editor")
        self.on_local_change()

    def empty_trash(self):
        def body():
            for n in [n for n in self.notes if n.is_trashed]:
                self.repo.delete_forever(n)
            self.notes = [n for n in self.notes if not n.is_trashed]
        self._perform(body)
        if self.nav == TRASH:
            self.selected_id = None
        self.changed("notes", "list", "counts", "editor")
        self.on_local_change()

    # MARK: Bloques

    def insert_block(self, block: Block, focus_key: str):
        """Inserta un bloque detrás del bloque activo (o al final) y le da el foco."""
        id = self._selected_id
        if id is None:
            return
        self._register_undo(id, "Insertar bloque")
        # Si el cursor está dentro de un texto, el bloque entra justo ahí y el resto del texto pasa a un párrafo nuevo.
        split = None
        note = self.note(id)
        active = self.active_block_id
        if active and note and any(b.id == active and b.is_text for b in note.blocks):
            split = self.split_active_text()

        def change(n: Note):
            at = len(n.blocks)
            i = next((k for k, b in enumerate(n.blocks) if b.id == active), None) if active else None
            if i is not None:
                if split and (inline_html.plain_text(split[0]) or inline_html.plain_text(split[1])):
                    has_before = bool(inline_html.plain_text(split[0]))
                    if has_before:
                        n.blocks[i].html = split[0]
                    else:
                        n.blocks.pop(i)
                    at = i + 1 if has_before else i
                    n.blocks.insert(at, block)
                    if inline_html.plain_text(split[1]):
                        n.blocks.insert(at + 1, Block.paragraph(split[1]))
                    self.ensure_trailing_paragraph(n)
                    return
                # Un párrafo vacío activo se sustituye por el bloque nuevo.
                b = n.blocks[i]
                if b.is_text and not inline_html.plain_text(b.html or "") and (len(n.blocks) > 1 or block.is_text):
                    n.blocks.pop(i)
                    at = i
                else:
                    at = i + 1
            elif n.blocks and n.blocks[-1].type == P and not inline_html.plain_text(n.blocks[-1].html or ""):
                n.blocks.pop()
                at = len(n.blocks)
            n.blocks.insert(at, block)
            self.ensure_trailing_paragraph(n)

        self.update(id, change)
        self.active_block_id = block.id
        self.set_focus(FocusTarget(id, focus_key))

    def remove_block(self, block_id: str, note_id: str):
        self._register_undo(note_id, "Eliminar bloque")
        focus_id = []

        def change(n: Note):
            i = next((k for k, b in enumerate(n.blocks) if b.id == block_id), None)
            if i is None:
                return
            n.blocks.pop(i)
            if not n.blocks:
                n.blocks = [Block.paragraph()]
            self.ensure_trailing_paragraph(n)
            focus_id.append(n.blocks[max(0, i - 1)].id)
        self.update(note_id, change)
        if focus_id:
            self.set_focus(FocusTarget(note_id, "block:" + focus_id[0]))

    def insert_divider(self, block_id: str, before: str, after: str, note_id: str):
        """`---` + Intro en un párrafo: lo parte en texto anterior, línea horizontal y texto posterior."""
        self._register_undo(note_id, "Insertar línea")
        focus_id = []

        def change(n: Note):
            i = next((k for k, b in enumerate(n.blocks) if b.id == block_id), None)
            if i is None:
                return
            at = i + 1
            if not inline_html.plain_text(before):
                n.blocks[i] = Block.divider()
            else:
                n.blocks[i].html = before
                n.blocks.insert(at, Block.divider())
                at += 1
            # Si no queda texto detrás y ya hay un párrafo vacío debajo, se reutiliza.
            if (not inline_html.plain_text(after) and at < len(n.blocks) and n.blocks[at].type == P
                    and not inline_html.plain_text(n.blocks[at].html or "")):
                focus_id.append(n.blocks[at].id)
            else:
                p = Block.paragraph(after if inline_html.plain_text(after) else "")
                n.blocks.insert(at, p)
                focus_id.append(p.id)
        self.update(note_id, change)
        if focus_id:
            self.active_block_id = focus_id[0]
            self.set_focus(FocusTarget(note_id, "block:" + focus_id[0]))

    # MARK: Deshacer

    def _register_undo(self, note_id: str, name: str):
        """Guarda los bloques actuales de la nota para deshacer cambios de estructura (insertar o quitar bloques)."""
        n = self.note(note_id)
        if n is None:
            return
        self._undo.append((note_id, [b.copy() for b in n.blocks], name))
        del self._undo[:-100]
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self):
        self._restore(self._undo, self._redo)

    def redo(self):
        self._restore(self._redo, self._undo)

    def _restore(self, source: list, target: list):
        if not source:
            return
        note_id, blocks, name = source.pop()
        current = self.note(note_id)
        if current is not None:
            target.append((note_id, [b.copy() for b in current.blocks], name))
        self.all_selected_note_id = None
        self.update(note_id, lambda n: setattr(n, "blocks", [b.copy() for b in blocks]))
        if note_id != self._selected_id:
            self.select_note(note_id)
        if blocks:
            self.active_block_id = blocks[0].id
            self.set_focus(FocusTarget(note_id, self.focus_key(blocks[0], last=False), at_start=True))

    # MARK: Selección de todos los bloques

    def select_all_blocks(self):
        if self._selected_id is None:
            return
        self.focus = None
        self.all_selected_note_id = self._selected_id
        self.changed("allselected")

    def clear_all_selected(self):
        if self.all_selected_note_id is not None:
            self.all_selected_note_id = None
            self.changed("allselected")

    def plain_text_of(self, note_id: str) -> str:
        """Texto plano de todos los bloques, para copiar."""
        n = self.note(note_id)
        if n is None:
            return ""
        out = []
        for b in n.blocks:
            if b.type == TODO:
                out.append("\n".join("• " + i.t for i in b.items or []))
            elif b.type == CODE:
                out.append(b.text or "")
            elif b.type == LINK:
                out.append(b.url or "")
            elif b.type == HR:
                out.append("---")
            else:
                out.append(b.plain_text)
        return "\n".join(out)

    def replace_all_blocks(self, note_id: str, text: str = ""):
        """Sustituye todos los bloques por un párrafo (vacío o con el texto tecleado) y lo enfoca."""
        p = Block.paragraph(inline_html.escape(text))
        self._register_undo(note_id, "Escribir" if text else "Eliminar todo")
        self.update(note_id, lambda n: setattr(n, "blocks", [p]))
        self.all_selected_note_id = None
        self.active_block_id = p.id
        self.set_focus(FocusTarget(note_id, "block:" + p.id))
        self.changed("allselected")

    def focus_end(self, note_id: str):
        """Clic en la zona vacía del editor: cursor al final del último bloque (siempre hay un párrafo al final)."""
        n = self.note(note_id)
        if n is None or n.is_trashed:
            return
        if not n.blocks or n.blocks[-1].type != P:
            self.update(note_id, self.ensure_trailing_paragraph)
            n = self.note(note_id)
        last = n.blocks[-1]
        self.clear_all_selected()
        self.active_block_id = last.id
        self.set_focus(FocusTarget(note_id, self.focus_key(last, last=True)))

    # MARK: Navegación con flechas

    @staticmethod
    def focus_key(b: Block, last: bool) -> str:
        """Clave de foco de un bloque; en las listas, el primer o el último elemento."""
        if b.type == TODO:
            return f"todo:{b.id}:{max(0, len(b.items or [None]) - 1) if last else 0}"
        if b.type == LINK:
            return "url:" + b.id
        if b.type == IMG:
            return "caption:" + (b.attachment_id or "")
        if b.type == HR:
            return "hr:" + b.id
        return "block:" + b.id

    def move_focus(self, block_id: Optional[str], up: bool, note_id: str, item: Optional[int] = None):
        """↑/↓ en el borde de un bloque: pasa al bloque anterior o siguiente (o al título).
        `block_id is None` es el título. `item` es el elemento actual si el bloque es una lista."""
        n = self.note(note_id)
        if n is None:
            return
        if block_id is not None:
            i = next((k for k, b in enumerate(n.blocks) if b.id == block_id), None)
            if i is None:
                return
            b = n.blocks[i]
            if b.type == TODO and item is not None:
                nxt = item + (-1 if up else 1)
                if 0 <= nxt < len(b.items or []):
                    self.set_focus(FocusTarget(note_id, f"todo:{b.id}:{nxt}"))
                    return
            target = i + (-1 if up else 1)
            if target < 0:
                self.set_focus(FocusTarget(note_id, "title"))
                return
        else:
            if up:
                return
            target = 0
        if not 0 <= target < len(n.blocks):
            return
        b = n.blocks[target]
        self.active_block_id = b.id
        self.set_focus(FocusTarget(note_id, self.focus_key(b, last=up), at_start=not up))

    def exit_list(self, block_id: str, item: int, note_id: str):
        """Intro en un elemento vacío de una lista: termina la lista y sigue en un párrafo.
        Si quedaban elementos debajo, pasan a una lista nueva tras el párrafo."""
        self._register_undo(note_id, "Terminar lista")
        focus_id = []

        def change(n: Note):
            i = next((k for k, b in enumerate(n.blocks) if b.id == block_id), None)
            if i is None:
                return
            items = n.blocks[i].items or []
            if not 0 <= item < len(items):
                return
            before, after = items[:item], items[item + 1:]
            at = i + 1
            if not before:
                n.blocks.pop(i)
                at = i
            else:
                n.blocks[i].items = before
            # Si justo debajo ya hay un párrafo vacío, se reutiliza.
            if (not after and at < len(n.blocks) and n.blocks[at].type == P
                    and not inline_html.plain_text(n.blocks[at].html or "")):
                focus_id.append(n.blocks[at].id)
            else:
                p = Block.paragraph()
                n.blocks.insert(at, p)
                if after:
                    n.blocks.insert(at + 1, Block.todo(after))
                focus_id.append(p.id)
            self.ensure_trailing_paragraph(n)
        self.update(note_id, change)
        if focus_id:
            self.active_block_id = focus_id[0]
            self.set_focus(FocusTarget(note_id, "block:" + focus_id[0]))

    def toggle_heading(self):
        """Alterna el bloque activo entre párrafo y encabezado."""
        if self._selected_id is None or self.active_block_id is None:
            return

        def change(b: Block):
            if b.type in ("p", "h"):
                b.type = "h" if b.type == "p" else "p"
        self.update_block(self._selected_id, self.active_block_id, change)

    @staticmethod
    def ensure_trailing_paragraph(n: Note):
        """Siempre hay un párrafo al final para poder seguir escribiendo tras un bloque especial."""
        if not n.blocks or n.blocks[-1].type != P:
            n.blocks.append(Block.paragraph())

    # MARK: Imágenes

    def add_image(self, path: str):
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
        id = new_id()
        file_name = f"{id}.{ext}"

        def body():
            os.makedirs(self.attachments_dir, exist_ok=True)
            shutil.copyfile(path, os.path.join(self.attachments_dir, file_name))
            mime = {"jpg": "image/jpeg", "svg": "image/svg+xml"}.get(ext) or mimetypes.guess_type(path)[0] or f"image/{ext}"
            self.repo.insert_attachment(Attachment(id=id, note_id=self._selected_id, file_name=file_name, mime=mime,
                                                   uploaded=False))
            self.insert_block(Block.image(id), "caption:" + id)
        self._perform(body)

    def local_image_path(self, attachment_id: str) -> Optional[str]:
        try:
            att = self.repo.attachment(attachment_id)
        except Exception:  # noqa: BLE001
            return None
        if att is None:
            return None
        path = os.path.join(self.attachments_dir, att.file_name)
        return path if os.path.exists(path) else None

    def attachments_changed(self):
        self.attachments_version += 1
        self.changed("attachments")

    # MARK: Libretas

    def create_notebook(self, name: str) -> Optional[Notebook]:
        trimmed = name.strip()
        if not trimmed:
            return None
        existing = next((nb for nb in self.notebooks if fold(nb.name) == fold(trimmed)), None)
        if existing:
            return existing
        created = []

        def body():
            created.append(self.repo.save_notebook(Notebook(name=trimmed, sort=len(self.notebooks))))
            self.notebooks = self.repo.notebooks()
        self._perform(body)
        self.changed("notebooks", "counts")
        self.on_local_change()
        return created[0] if created else None

    def rename_notebook(self, notebook: Notebook, name: str):
        trimmed = name.strip()
        if not trimmed:
            return

        def body():
            self.repo.save_notebook(Notebook(**{**notebook.__dict__, "name": trimmed}))
            self.notebooks = self.repo.notebooks()
        self._perform(body)
        self.changed("notebooks", "nav", "list", "editor")
        self.on_local_change()

    def move_notebook(self, id: str, target: str):
        """Coloca `id` en la posición que ocupa `target` (arrastrar y soltar en la barra lateral)."""
        ids = [nb.id for nb in self.notebooks]
        if id == target or id not in ids or target not in ids:
            return
        frm, to = ids.index(id), ids.index(target)
        ids.insert(to, ids.pop(frm))

        def body():
            self.repo.reorder_notebooks(ids)
            self.notebooks = self.repo.notebooks()
        self._perform(body)
        self.changed("notebooks")
        self.on_local_change()

    def delete_notebook(self, notebook: Notebook):
        self._perform(lambda: self.repo.delete_notebook(notebook))
        if self.nav == notebook_nav(notebook.id):
            self.nav = ALL
            self.changed("nav")
        self.reload()
        self.on_local_change()

    def move(self, note_id: str, notebook_id: str):
        self.update(note_id, lambda n: setattr(n, "notebook_id", notebook_id))
