"""Integración con el sistema: rutas XDG, ajustes y el token en el llavero (Secret Service)."""
from __future__ import annotations

import json
import os
from typing import Optional

APP_ID = "com.jmarreros.misnotas"
RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def _xdg(var: str, fallback: str) -> str:
    return os.environ.get(var) or os.path.join(os.path.expanduser("~"), fallback)


DATA_DIR = os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), "misnotas")
CONFIG_DIR = os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "misnotas")
ATTACHMENTS_DIR = os.path.join(DATA_DIR, "attachments")


class Config:
    """Ajustes sencillos en ~/.config/misnotas/config.json (equivalente a UserDefaults)."""

    _path = os.path.join(CONFIG_DIR, "config.json")

    @classmethod
    def _load(cls) -> dict:
        try:
            with open(cls._path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    @classmethod
    def get(cls, key: str) -> Optional[str]:
        return cls._load().get(key)

    @classmethod
    def set(cls, key: str, value: Optional[str]):
        data = cls._load()
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = cls._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, cls._path)


class Keychain:
    """Guarda el token de la API en el llavero del sistema (gnome-keyring, KWallet…) mediante libsecret.
    Si no hay servicio de secretos disponible, recurre a un archivo legible solo por el usuario."""

    _fallback = os.path.join(CONFIG_DIR, "token")
    _schema = None

    @classmethod
    def _secret(cls):
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
        except (ImportError, ValueError):
            return None, None
        if cls._schema is None:
            cls._schema = Secret.Schema.new(APP_ID, Secret.SchemaFlags.NONE,
                                            {"account": Secret.SchemaAttributeType.STRING})
        return Secret, cls._schema

    @classmethod
    def token(cls) -> Optional[str]:
        Secret, schema = cls._secret()
        if Secret:
            try:
                value = Secret.password_lookup_sync(schema, {"account": "api-token"}, None)
                if value:
                    return value
            except Exception:
                pass
        try:
            with open(cls._fallback) as f:
                return f.read().strip() or None
        except OSError:
            return None

    @classmethod
    def set_token(cls, token: Optional[str]):
        Secret, schema = cls._secret()
        stored = False
        if Secret:
            try:
                Secret.password_clear_sync(schema, {"account": "api-token"}, None)
                if token:
                    stored = Secret.password_store_sync(schema, {"account": "api-token"}, Secret.COLLECTION_DEFAULT,
                                                        "Mis Notas: token de la API", token, None)
                else:
                    stored = True
            except Exception:
                stored = False
        if stored or not token:
            try:
                os.remove(cls._fallback)
            except OSError:
                pass
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        fd = os.open(cls._fallback, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token)
