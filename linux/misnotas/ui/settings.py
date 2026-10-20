"""Ajustes del servidor: dirección de la API, token, estado y desconexión.
Al cambiar de servidor, la app vuelve a enviar todas las notas para que el nuevo quede completo."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from gi.repository import Gtk, Pango

from ..platform import Config, Keychain
from ..sync import SERVER_URL_KEY, normalize
from .sidebar import SyncStatusRow
from .widgets import confirm, hspacer, text_button

if TYPE_CHECKING:
    from ..sync import SyncCoordinator


class SettingsWindow(Gtk.Window):
    def __init__(self, parent: Optional[Gtk.Window], sync: "SyncCoordinator"):
        super().__init__(modal=True, transient_for=parent, resizable=False, default_width=500, title="Ajustes")
        self.sync = sync
        self.add_css_class("mn-dialog")
        self.set_titlebar(Gtk.Box(visible=False))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=22, margin_bottom=20,
                      margin_start=24, margin_end=24)
        self.set_child(box)

        title = Gtk.Label(label="SERVIDOR", xalign=0)
        title.add_css_class("mn-dialog-title")
        box.append(title)

        box.append(self._label("Dirección"))
        self.url = Gtk.Entry(placeholder_text="https://notas.tudominio.com", text=self._saved_url())
        self.url.connect("changed", lambda *_: self._refresh_buttons())
        box.append(self.url)
        box.append(self._label("Token"))
        self.token = Gtk.PasswordEntry(placeholder_text="Pega el token de misnotas:token", show_peek_icon=True)
        self.token.set_text(Keychain.token() or "")
        self.token.connect("changed", lambda *_: self._refresh_buttons())
        box.append(self.token)
        for line in ("La dirección base de la API, sin /api. Para probar en local: http://127.0.0.1:8000.",
                     "Genera el token en el servidor con php artisan misnotas:token tu@correo.com."):
            help = Gtk.Label(label=line, xalign=0, wrap=True, max_width_chars=60)
            help.add_css_class("mn-help")
            box.append(help)

        status_title = Gtk.Label(label="ESTADO", xalign=0, margin_top=8)
        status_title.add_css_class("mn-section-title")
        box.append(status_title)
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(self.status_box)

        buttons = Gtk.Box(spacing=8, margin_top=8)
        self.test = text_button("Probar conexión", self._test, "mn-secondary")
        buttons.append(self.test)
        self.disconnect = text_button("Desconectar", self._disconnect, "mn-secondary", "destructive")
        buttons.append(self.disconnect)
        buttons.append(hspacer())
        self.save = text_button("Guardar y conectar", self._save, "mn-primary")
        buttons.append(self.save)
        box.append(buttons)
        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=60)
        self.message.add_css_class("mn-message")
        box.append(self.message)
        self.set_default_widget(self.save)
        self.url.set_activates_default(True)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"),
                                          Gtk.CallbackAction.new(lambda *_: (self.close(), True)[1])))
        self.add_controller(esc)
        self._testing = False
        self._refresh_status()
        self._refresh_buttons()

    @staticmethod
    def _label(text: str) -> Gtk.Label:
        l = Gtk.Label(label=text, xalign=0)
        l.add_css_class("mn-field-label")
        return l

    @staticmethod
    def _saved_url() -> str:
        return Config.get(SERVER_URL_KEY) or ""

    def _has_changes(self) -> bool:
        return (normalize(self.url.get_text()) != self._saved_url()
                or self.token.get_text().strip() != (Keychain.token() or ""))

    def _refresh_buttons(self):
        url, token = self.url.get_text().strip(), self.token.get_text().strip()
        self.test.set_sensitive(bool(url and token) and not self._testing)
        self.save.set_sensitive(bool(url and token) and self._has_changes())
        self.disconnect.set_visible(bool(self._saved_url()))

    def _refresh_status(self):
        while (child := self.status_box.get_first_child()) is not None:
            self.status_box.remove(child)
        if self.sync.status[0] == "not_configured":
            l = Gtk.Label(label="Sin servidor: las notas solo se guardan en este equipo.", xalign=0, wrap=True)
            l.add_css_class("mn-message")
            self.status_box.append(l)
        else:
            l = Gtk.Label(label=f"Conectado a {self._saved_url()}", xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
            l.add_css_class("mn-message")
            self.status_box.append(l)
            self.status_box.append(SyncStatusRow(self.sync, lambda: None))

    def _test(self):
        self._testing = True
        self.message.set_label("Probando…")
        self._refresh_buttons()

        def done(msg: str):
            self._testing = False
            self.message.set_label(msg)
            self._refresh_buttons()
        self.sync.test_connection(self.url.get_text(), self.token.get_text(), done)

    def _save(self):
        changing_server = bool(self._saved_url()) and self._has_changes()
        self.sync.save(self.url.get_text(), self.token.get_text())
        self.url.set_text(self._saved_url())
        self.message.set_label("Guardado. Se enviarán todas las notas al servidor nuevo." if changing_server
                               else "Guardado.")
        self._refresh_status()
        self._refresh_buttons()

    def _disconnect(self):
        def done():
            self.sync.disconnect()
            self.url.set_text("")
            self.token.set_text("")
            self.message.set_label("Desconectado. Tus notas siguen en este equipo.")
            self._refresh_status()
            self._refresh_buttons()
        confirm(self, "¿Desconectar del servidor?",
                "Las notas no se borran: siguen en este equipo y se enviarán cuando vuelvas a conectar.",
                "Desconectar", done)
