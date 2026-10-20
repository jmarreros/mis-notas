"""Cliente de la API Laravel (`/api/sync` y `/api/attachments`)."""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from .models import Attachment, Note, Notebook


@dataclass
class PullResponse:
    rev: int
    notebooks: list[Notebook]
    notes: list[Note]

    @staticmethod
    def from_json(d: dict) -> "PullResponse":
        return PullResponse(rev=int(d.get("rev") or 0),
                            notebooks=[Notebook.from_json(x) for x in d.get("notebooks") or []],
                            notes=[Note.from_json(x) for x in d.get("notes") or []])


# Registros rechazados porque el servidor tiene una versión más reciente.
PushResponse = PullResponse


class SyncTransport(Protocol):
    """Lo que el `SyncEngine` necesita del servidor."""

    def pull(self, since: int) -> PullResponse: ...
    def push(self, notebooks: list[Notebook], notes: list[Note]) -> PushResponse: ...
    def upload(self, attachment: Attachment, data: bytes) -> None: ...
    def download(self, attachment_id: str) -> bytes: ...


class APIError(Exception):
    pass


class NotConfigured(APIError):
    def __str__(self):
        return "Configura el servidor en Ajustes."


class Unauthorized(APIError):
    def __str__(self):
        return "Token no válido."


class HTTPError(APIError):
    def __init__(self, code: int, message: str):
        super().__init__(code, message)
        self.code, self.message = code, message

    def __str__(self):
        return f"Error del servidor ({self.code}): {self.message}"


class Offline(APIError):
    """No hay conexión con el servidor (red caída, DNS, tiempo agotado…)."""

    def __str__(self):
        return "Sin conexión con el servidor."


class APIClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, path: str, method: str = "GET", body: Optional[bytes] = None,
                 content_type: Optional[str] = None, timeout: float = 30) -> bytes:
        req = urllib.request.Request(f"{self.base_url}/api/{path}", data=body, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise Unauthorized() from e
            data = e.read()
            try:
                msg = json.loads(data).get("message")
            except (ValueError, AttributeError):
                msg = None
            raise HTTPError(e.code, msg or http.client.responses.get(e.code, "error")) from e
        except ssl.SSLError as e:
            raise APIError(f"Error de TLS: {e}") from e
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            raise Offline() from e

    def pull(self, since: int) -> PullResponse:
        return PullResponse.from_json(json.loads(self._request(f"sync?since={int(since)}")))

    def push(self, notebooks: list[Notebook], notes: list[Note]) -> PushResponse:
        body = json.dumps({"notebooks": [n.to_json() for n in notebooks], "notes": [n.to_json() for n in notes]},
                          ensure_ascii=False).encode()
        return PullResponse.from_json(json.loads(self._request("sync", "POST", body, "application/json")))

    def upload(self, attachment: Attachment, data: bytes) -> None:
        boundary = f"mn-{uuid.uuid4()}"
        parts = []

        def field(name, value):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

        field("id", attachment.id)
        if attachment.note_id:
            field("note_id", attachment.note_id)
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{attachment.file_name}"'
                      f'\r\nContent-Type: {attachment.mime}\r\n\r\n').encode())
        parts.append(data)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        self._request("attachments", "POST", b"".join(parts), f"multipart/form-data; boundary={boundary}", timeout=120)

    def download(self, attachment_id: str) -> bytes:
        return self._request(f"attachments/{urllib.parse.quote(attachment_id)}")
