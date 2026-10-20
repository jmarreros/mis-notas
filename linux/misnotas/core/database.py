"""Réplica local en SQLite. La app trabaja contra esta base y el `SyncEngine` la reconcilia con el servidor.

Toda escritura del usuario marca el registro como `dirty` para que se envíe.
La conexión se comparte entre el hilo de la interfaz y el de sincronización, protegida por un cerrojo.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterable, Optional

from .models import Attachment, Block, Note, Notebook, now_ms
from .text import fold

_MIGRATIONS = [
    # v1
    """
    CREATE TABLE notebook (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0,
        createdAt INTEGER NOT NULL, updatedAt INTEGER NOT NULL, deletedAt INTEGER,
        dirty INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE note (
        id TEXT PRIMARY KEY, notebookId TEXT, title TEXT NOT NULL DEFAULT '', blocks TEXT NOT NULL,
        createdAt INTEGER NOT NULL, updatedAt INTEGER NOT NULL, trashedAt INTEGER, deletedAt INTEGER,
        favorite INTEGER NOT NULL DEFAULT 0, dirty INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX note_dirty ON note(dirty);
    CREATE TABLE attachment (
        id TEXT PRIMARY KEY, noteId TEXT, fileName TEXT NOT NULL, mime TEXT NOT NULL,
        uploaded INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    -- Índice de búsqueda. unicode61 ignora mayúsculas y tildes ("japon" encuentra "Japón").
    CREATE VIRTUAL TABLE noteSearch USING fts5(noteId UNINDEXED, title, body, tokenize = 'unicode61');
    """,
]


class AppDatabase:
    def __init__(self, path: str = ":memory:"):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    @staticmethod
    def on_disk(directory: str) -> "AppDatabase":
        os.makedirs(directory, exist_ok=True)
        return AppDatabase(os.path.join(directory, "notas.sqlite"))

    def _migrate(self):
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(_MIGRATIONS[version:], start=version + 1):
            with self.transaction() as c:
                for statement in _statements(sql):
                    c.execute(statement)
                c.execute(f"PRAGMA user_version = {i}")

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def close(self):
        with self.lock:
            self.conn.close()

    def read(self, sql: str, args: Iterable = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(args)).fetchall()


def _statements(script: str) -> list[str]:
    script = re.sub(r"--[^\n]*", "", script)
    return [s.strip() for s in script.split(";") if s.strip()]


# MARK: - Filas ↔ modelos

def _notebook(r: sqlite3.Row) -> Notebook:
    return Notebook(id=r["id"], name=r["name"], sort=r["sort"], created_at=r["createdAt"], updated_at=r["updatedAt"],
                    deleted_at=r["deletedAt"], dirty=bool(r["dirty"]))


def _note(r: sqlite3.Row) -> Note:
    blocks = [Block.from_json(b) for b in json.loads(r["blocks"] or "[]")]
    return Note(id=r["id"], notebook_id=r["notebookId"], title=r["title"], blocks=blocks,
                created_at=r["createdAt"], updated_at=r["updatedAt"], trashed_at=r["trashedAt"],
                deleted_at=r["deletedAt"], favorite=bool(r["favorite"]), dirty=bool(r["dirty"]))


def _attachment(r: sqlite3.Row) -> Attachment:
    return Attachment(id=r["id"], note_id=r["noteId"], file_name=r["fileName"], mime=r["mime"],
                      uploaded=bool(r["uploaded"]))


def _save_notebook(c: sqlite3.Connection, nb: Notebook):
    c.execute("INSERT OR REPLACE INTO notebook (id, name, sort, createdAt, updatedAt, deletedAt, dirty) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)",
              (nb.id, nb.name, nb.sort, nb.created_at, nb.updated_at, nb.deleted_at, int(nb.dirty)))


def _save_note(c: sqlite3.Connection, n: Note):
    c.execute("INSERT OR REPLACE INTO note (id, notebookId, title, blocks, createdAt, updatedAt, trashedAt, deletedAt, "
              "favorite, dirty) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (n.id, n.notebook_id, n.title, json.dumps([b.to_json() for b in n.blocks], ensure_ascii=False),
               n.created_at, n.updated_at, n.trashed_at, n.deleted_at, int(n.favorite), int(n.dirty)))
    _index(c, n)


def _index(c: sqlite3.Connection, n: Note):
    c.execute("DELETE FROM noteSearch WHERE noteId = ?", (n.id,))
    if n.deleted_at is None:
        c.execute("INSERT INTO noteSearch (noteId, title, body) VALUES (?, ?, ?)", (n.id, n.title, n.body_text))


def fts_pattern(query: str) -> Optional[str]:
    """Patrón FTS5 que exige todos los prefijos de la consulta ("kio nar" → "kio"* "nar"*)."""
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None
    return " ".join('"' + t.replace('"', '""') + '"*' for t in tokens)


class SyncMerge:
    """Regla de fusión: last-write-wins por `updatedAt`, pero un cambio local pendiente
    solo se pisa si el remoto es igual o más reciente."""

    @staticmethod
    def should_apply(remote_updated_at: int, local: Optional[tuple[int, bool]]) -> bool:
        if local is None:
            return True
        updated_at, dirty = local
        if not dirty:
            return True
        return remote_updated_at >= updated_at


class NotesRepository:
    def __init__(self, db: AppDatabase):
        self.db = db

    # MARK: Lectura

    def notebooks(self) -> list[Notebook]:
        nbs = [_notebook(r) for r in self.db.read("SELECT * FROM notebook WHERE deletedAt IS NULL")]
        nbs.sort(key=lambda nb: (nb.sort, fold(nb.name)))
        return nbs

    def notes(self) -> list[Note]:
        """Todas las notas vivas (también las de la Papelera), más recientes primero."""
        return [_note(r) for r in self.db.read("SELECT * FROM note WHERE deletedAt IS NULL ORDER BY updatedAt DESC")]

    def note(self, id: str) -> Optional[Note]:
        rows = self.db.read("SELECT * FROM note WHERE id = ?", (id,))
        return _note(rows[0]) if rows else None

    def notebook(self, id: str) -> Optional[Notebook]:
        rows = self.db.read("SELECT * FROM notebook WHERE id = ?", (id,))
        return _notebook(rows[0]) if rows else None

    def search(self, query: str) -> set[str]:
        """IDs de las notas que coinciden con todos los prefijos de la consulta."""
        pattern = fts_pattern(query)
        if not pattern:
            return set()
        return {r[0] for r in self.db.read("SELECT noteId FROM noteSearch WHERE noteSearch MATCH ?", (pattern,))}

    # MARK: Escritura local

    def save_note(self, note: Note, touch: bool = True) -> Note:
        """Guarda una nota editada por el usuario. Actualiza `updatedAt` salvo que se indique otra fecha."""
        n = note.copy()
        if touch:
            n.updated_at = max(now_ms(), note.updated_at + 1)
        n.dirty = True
        with self.db.transaction() as c:
            _save_note(c, n)
        return n

    def save_notebook(self, notebook: Notebook) -> Notebook:
        nb = Notebook(**{**notebook.__dict__})
        nb.updated_at = max(now_ms(), notebook.updated_at + 1)
        nb.dirty = True
        with self.db.transaction() as c:
            _save_notebook(c, nb)
        return nb

    def reorder_notebooks(self, ids: list[str]):
        """Fija el orden manual de las libretas: `ids` es el orden deseado. Solo toca las que cambian."""
        with self.db.transaction() as c:
            now = now_ms()
            for index, id in enumerate(ids):
                rows = c.execute("SELECT * FROM notebook WHERE id = ?", (id,)).fetchall()
                if not rows:
                    continue
                nb = _notebook(rows[0])
                if nb.deleted_at is not None or nb.sort == index:
                    continue
                nb.sort = index
                nb.updated_at = max(now, nb.updated_at + 1)
                nb.dirty = True
                _save_notebook(c, nb)

    def insert(self, notes: list[Note], notebooks: list[Notebook] = ()):
        """Guarda varias notas en una sola transacción (importación). Respeta sus fechas."""
        with self.db.transaction() as c:
            for nb in notebooks:
                nb.dirty = True
                _save_notebook(c, nb)
            for n in notes:
                n.dirty = True
                _save_note(c, n)

    def delete_forever(self, note: Note):
        """Borrado definitivo: deja una lápida para propagarlo al servidor."""
        self.save_note(note.copy(deleted_at=now_ms(), blocks=[], title=""))

    def delete_notebook(self, notebook: Notebook):
        """Elimina una libreta y manda sus notas a la Papelera."""
        with self.db.transaction() as c:
            now = now_ms()
            nb = Notebook(**{**notebook.__dict__})
            nb.deleted_at = now
            nb.updated_at = max(now, nb.updated_at + 1)
            nb.dirty = True
            _save_notebook(c, nb)
            rows = c.execute("SELECT * FROM note WHERE notebookId = ? AND deletedAt IS NULL", (notebook.id,)).fetchall()
            for r in rows:
                n = _note(r)
                if n.trashed_at is not None:
                    continue
                n.trashed_at = now
                n.updated_at = max(now, n.updated_at + 1)
                n.dirty = True
                _save_note(c, n)

    # MARK: Adjuntos

    def insert_attachment(self, a: Attachment):
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO attachment (id, noteId, fileName, mime, uploaded) VALUES (?, ?, ?, ?, ?)",
                      (a.id, a.note_id, a.file_name, a.mime, int(a.uploaded)))

    def attachment(self, id: str) -> Optional[Attachment]:
        rows = self.db.read("SELECT * FROM attachment WHERE id = ?", (id,))
        return _attachment(rows[0]) if rows else None

    def pending_uploads(self) -> list[Attachment]:
        return [_attachment(r) for r in self.db.read("SELECT * FROM attachment WHERE uploaded = 0")]

    def mark_uploaded(self, id: str):
        with self.db.transaction() as c:
            c.execute("UPDATE attachment SET uploaded = 1 WHERE id = ?", (id,))

    # MARK: Vistas recientes (solo locales, no se sincronizan)

    def recent_ids(self) -> list[str]:
        rows = self.db.read("SELECT value FROM meta WHERE key = 'recentIds'")
        try:
            return json.loads(rows[0][0]) if rows else []
        except (ValueError, TypeError):
            return []

    def set_recent_ids(self, ids: list[str]):
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('recentIds', ?)", (json.dumps(ids),))

    # MARK: Sincronización

    def last_rev(self) -> int:
        rows = self.db.read("SELECT value FROM meta WHERE key = 'lastRev'")
        try:
            return int(rows[0][0]) if rows else 0
        except (ValueError, TypeError):
            return 0

    def reset_sync_state(self):
        """Al cambiar de servidor: todo vuelve a enviarse (notas, libretas e imágenes) y se descarga
        desde el principio. Si el servidor ya tenía los datos, gana la versión más reciente."""
        with self.db.transaction() as c:
            c.execute("UPDATE notebook SET dirty = 1")
            c.execute("UPDATE note SET dirty = 1")
            c.execute("UPDATE attachment SET uploaded = 0")
            c.execute("DELETE FROM meta WHERE key = 'lastRev'")

    def dirty_records(self) -> tuple[list[Notebook], list[Note]]:
        with self.db.lock:
            return ([_notebook(r) for r in self.db.read("SELECT * FROM notebook WHERE dirty = 1")],
                    [_note(r) for r in self.db.read("SELECT * FROM note WHERE dirty = 1")])

    def mark_clean(self, notebooks: list[Notebook], notes: list[Note]):
        """Limpia `dirty` solo si el registro no cambió mientras se enviaba."""
        with self.db.transaction() as c:
            for nb in notebooks:
                c.execute("UPDATE notebook SET dirty = 0 WHERE id = ? AND updatedAt = ?", (nb.id, nb.updated_at))
            for n in notes:
                c.execute("UPDATE note SET dirty = 0 WHERE id = ? AND updatedAt = ?", (n.id, n.updated_at))

    def apply_remote(self, notebooks: list[Notebook], notes: list[Note], rev: Optional[int]) -> int:
        """Aplica registros del servidor según `SyncMerge`. Devuelve cuántos cambiaron localmente."""
        changed = 0
        with self.db.transaction() as c:
            for remote in notebooks:
                rows = c.execute("SELECT * FROM notebook WHERE id = ?", (remote.id,)).fetchall()
                local = _notebook(rows[0]) if rows else None
                if not SyncMerge.should_apply(remote.updated_at, (local.updated_at, local.dirty) if local else None):
                    continue
                remote.dirty = False
                if remote != local:
                    changed += 1
                _save_notebook(c, remote)
            for remote in notes:
                rows = c.execute("SELECT * FROM note WHERE id = ?", (remote.id,)).fetchall()
                local = _note(rows[0]) if rows else None
                if not SyncMerge.should_apply(remote.updated_at, (local.updated_at, local.dirty) if local else None):
                    continue
                remote.dirty = False
                if remote != local:
                    changed += 1
                _save_note(c, remote)
            if rev is not None:
                c.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('lastRev', ?)", (str(rev),))
        return changed
