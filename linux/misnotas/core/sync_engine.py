"""Un ciclo de sincronización: subir imágenes pendientes → enviar cambios locales →
adoptar los rechazados → descargar todo lo nuevo desde el último `rev`.

Es síncrono: la interfaz lo ejecuta en un hilo aparte.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .api import SyncTransport
from .database import NotesRepository
from .models import Attachment


@dataclass
class SyncResult:
    pushed: int
    pulled: int


class SyncEngine:
    def __init__(self, repo: NotesRepository, transport: SyncTransport, attachments_dir: str):
        self.repo = repo
        self.transport = transport
        self.attachments_dir = attachments_dir

    def sync(self) -> SyncResult:
        for att in self.repo.pending_uploads():
            try:
                with open(os.path.join(self.attachments_dir, att.file_name), "rb") as f:
                    data = f.read()
            except OSError:
                continue
            self.transport.upload(att, data)
            self.repo.mark_uploaded(att.id)

        notebooks, notes = self.repo.dirty_records()
        changed = 0
        if notebooks or notes:
            res = self.transport.push(notebooks, notes)
            self.repo.mark_clean(notebooks, notes)
            changed += self.repo.apply_remote(res.notebooks, res.notes, None)

        pulled = self.transport.pull(self.repo.last_rev())
        changed += self.repo.apply_remote(pulled.notebooks, pulled.notes, pulled.rev)
        return SyncResult(pushed=len(notebooks) + len(notes), pulled=changed)

    def fetch_attachment(self, id: str, extension: str = "png") -> str:
        """Descarga una imagen que no está en este equipo."""
        data = self.transport.download(id)
        file_name = f"{id}.{extension}"
        os.makedirs(self.attachments_dir, exist_ok=True)
        path = os.path.join(self.attachments_dir, file_name)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        self.repo.insert_attachment(Attachment(id=id, note_id=None, file_name=file_name, mime=f"image/{extension}",
                                               uploaded=True))
        return path
