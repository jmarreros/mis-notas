"""Decide cuándo sincronizar: al abrir, cada 30 s, 2 s después de cada edición y al recuperar la conexión.
Cada ciclo corre en un hilo aparte; el resultado vuelve al bucle principal de GLib."""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from gi.repository import Gio, GLib

from .core.api import APIClient, Offline
from .core.sync_engine import SyncEngine
from .platform import Config, Keychain
from .state import AppState

SERVER_URL_KEY = "serverURL"
# Huella del servidor y token con los que está sincronizada la réplica local.
# Se conserva al desconectar, para detectar luego un servidor distinto.
SYNCED_SERVER_KEY = "syncedServer"


class SyncCoordinator:
    # Estados: ("not_configured",), ("idle", timestamp|None), ("syncing",), ("offline",), ("error", msg)

    def __init__(self, state: AppState):
        self.state = state
        self.status: tuple = ("not_configured",)
        self._engine: Optional[SyncEngine] = None
        self._debounce: Optional[int] = None
        self._running = False
        self._again = False
        self._downloading: set[str] = set()
        self._listeners: list[Callable[[], None]] = []

        state.on_local_change = lambda: self.schedule_soon()
        monitor = Gio.NetworkMonitor.get_default()
        monitor.connect("network-changed", lambda m, available: available and self.schedule_soon(1))
        self.configure()
        GLib.timeout_add_seconds(30, self._tick)
        # Refresca el «Sincronizado hace…» de la barra lateral.
        GLib.timeout_add_seconds(30, lambda: (self._notify(), True)[1])

    def subscribe(self, fn: Callable[[], None]):
        self._listeners.append(fn)

    def _notify(self):
        for fn in list(self._listeners):
            fn()

    def _set_status(self, status: tuple):
        self.status = status
        self._notify()

    @property
    def server_url(self) -> str:
        return Config.get(SERVER_URL_KEY) or ""

    def configure(self):
        """Lee servidor y token y prepara el motor. Se llama al iniciar y al guardar los Ajustes."""
        url = self.server_url.strip()
        token = Keychain.token()
        if not url or not urlparse(url).scheme or not token:
            self._engine = None
            self._set_status(("not_configured",))
            return
        self._engine = SyncEngine(self.state.repo, APIClient(url, token), self.state.attachments_dir)
        self._set_status(("idle", None))
        self.sync_now()

    def _tick(self):
        self.sync_now()
        return True

    def schedule_soon(self, delay: float = 2):
        if self._debounce is not None:
            GLib.source_remove(self._debounce)

        def fire():
            self._debounce = None
            self.sync_now()
            return False
        self._debounce = GLib.timeout_add(int(delay * 1000), fire)

    def sync_now(self):
        engine = self._engine
        if engine is None:
            return
        if self._running:
            self._again = True
            return
        self._running = True
        self._set_status(("syncing",))

        def work():
            try:
                result = engine.sync()
                GLib.idle_add(self._finished, engine, result, None)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._finished, engine, None, e)
        threading.Thread(target=work, name="sync", daemon=True).start()

    def _finished(self, engine, result, error):
        self._running = False
        if engine is not self._engine:
            # Se cambió de servidor mientras tanto.
            if self._engine is not None:
                self.schedule_soon(0.2)
            return False
        if error is None:
            if result.pulled > 0:
                self.state.reload()
            self._set_status(("idle", time.time()))
        elif isinstance(error, Offline):
            self._set_status(("offline",))
        else:
            self._set_status(("error", str(error)))
        if self._again:
            self._again = False
            self.schedule_soon(0.2)
        return False

    def fetch_attachment(self, id: str):
        """Descarga una imagen creada en otro equipo."""
        engine = self._engine
        if engine is None or id in self._downloading:
            return
        self._downloading.add(id)

        def work():
            ok = False
            try:
                engine.fetch_attachment(id)
                ok = True
            except Exception:  # noqa: BLE001
                pass

            def done():
                self._downloading.discard(id)
                if ok:
                    self.state.attachments_changed()
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, name="attachment", daemon=True).start()

    def save(self, url: str, token: str):
        """Guarda servidor y token. Si cambian respecto a los guardados, se reinicia el estado de
        sincronización para que un servidor nuevo reciba todas las notas."""
        url = normalize(url)
        token = token.strip()
        identity = hashlib.sha256((url + "\n" + token).encode()).hexdigest()
        previous = Config.get(SYNCED_SERVER_KEY)
        if previous and previous != identity:
            try:
                self.state.repo.reset_sync_state()
            except Exception as e:  # noqa: BLE001
                self.state.on_error(str(e))
        Config.set(SYNCED_SERVER_KEY, identity)
        Config.set(SERVER_URL_KEY, url)
        Keychain.set_token(token)
        self.configure()

    def disconnect(self):
        """Deja de sincronizar. Las notas siguen en este equipo."""
        Config.set(SERVER_URL_KEY, None)
        Keychain.set_token(None)
        self.configure()

    @staticmethod
    def test_connection(url: str, token: str, done: Callable[[str], None]):
        """Comprueba servidor y token sin modificar nada. Llama a `done` en el bucle principal."""
        base = normalize(url)
        parsed = urlparse(base)
        if not parsed.scheme or not parsed.netloc:
            done("URL no válida.")
            return

        def work():
            try:
                r = APIClient(base, token.strip()).pull(2 ** 62)
                msg = f"Conexión correcta (revisión {r.rev})."
            except Exception as e:  # noqa: BLE001
                msg = str(e)
            GLib.idle_add(lambda: (done(msg), False)[1])
        threading.Thread(target=work, daemon=True).start()


def normalize(raw: str) -> str:
    """Acepta "midominio.com", "http://127.0.0.1:8000/" o ".../api": la app añade `/api` sola."""
    s = raw.strip()
    if not s:
        return ""
    s = s.rstrip("/")
    if s.lower().endswith("/api"):
        s = s[:-4]
    s = s.rstrip("/")
    if "://" not in s:
        local = (s.startswith("localhost") or s.startswith("127.") or s.startswith("192.168.") or s.startswith("10.")
                 or ".local" in s or ".test" in s)
        s = ("http://" if local else "https://") + s
    return s


def relative_sync_text(ts: float) -> str:
    """«Sincronizado hace 3 minutos», como `.relative(presentation: .named)` en español."""
    secs = max(0, int(time.time() - ts))
    if secs < 60:
        return "Sincronizado ahora"
    mins = secs // 60
    if mins < 60:
        return f"Sincronizado hace {mins} minuto{'s' if mins != 1 else ''}"
    hours = mins // 60
    if hours < 24:
        return f"Sincronizado hace {hours} hora{'s' if hours != 1 else ''}"
    days = hours // 24
    return "Sincronizado ayer" if days == 1 else f"Sincronizado hace {days} días"

