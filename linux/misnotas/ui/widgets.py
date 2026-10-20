"""Piezas comunes de la interfaz: botones de icono, filas de navegación, diálogos y formatos."""
from __future__ import annotations

import datetime as dt
import math
from typing import Callable, Optional

from gi.repository import Gdk, GLib, Gtk, Pango

from ..core.text import find_folded


def icon_button(icon: str, tooltip: str = "", action: Optional[Callable[[], None]] = None,
                *classes: str) -> Gtk.Button:
    """Botón de icono de 30×28 con fondo al pasar el ratón. No roba el foco al editor."""
    b = Gtk.Button(icon_name=icon)
    b.add_css_class("mn-icon")
    for c in classes:
        b.add_css_class(c)
    b.set_focus_on_click(False)
    b.set_can_focus(False)
    if tooltip:
        b.set_tooltip_text(tooltip)
    if action:
        b.connect("clicked", lambda *_: action())
    return b


def text_button(label: str, action: Callable[[], None], *classes: str) -> Gtk.Button:
    b = Gtk.Button(label=label)
    for c in classes:
        b.add_css_class(c)
    b.connect("clicked", lambda *_: action())
    return b


def on_click(widget: Gtk.Widget, fn: Callable[[Gtk.GestureClick, int, float, float], None], button: int = 1):
    g = Gtk.GestureClick(button=button)
    g.connect("released", lambda gest, n, x, y: fn(gest, n, x, y))
    widget.add_controller(g)
    return g


def on_right_click(widget: Gtk.Widget, fn: Callable[[float, float], None]):
    g = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
    g.connect("pressed", lambda gest, n, x, y: (gest.set_state(Gtk.EventSequenceState.CLAIMED), fn(x, y)))
    widget.add_controller(g)


class NavRow(Gtk.Box):
    """Fila de la barra lateral: icono, título y contador."""

    def __init__(self, icon: str, title: str, count: int, active: bool, action: Callable[[], None], tall: bool = False):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        self.add_css_class("mn-nav-row")
        if tall:
            self.add_css_class("tall")
        self.icon = Gtk.Image(icon_name=icon, pixel_size=14)
        self.label = Gtk.Label(label=title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.count = Gtk.Label(label=str(count))
        self.count.add_css_class("count")
        self.append(self.icon)
        self.append(self.label)
        self.append(self.count)
        self.set_active(active)
        self.action = action
        on_click(self, lambda *_: self.action())
        self.set_cursor(Gdk.Cursor.new_from_name("default"))

    def set_active(self, active: bool):
        (self.add_css_class if active else self.remove_css_class)("active")

    def set_values(self, title: str, count: int, active: bool):
        if self.label.get_label() != title:
            self.label.set_label(title)
        self.count.set_label(str(count))
        self.set_active(active)


def hspacer() -> Gtk.Widget:
    return Gtk.Box(hexpand=True)


def window_of(widget: Gtk.Widget) -> Optional[Gtk.Window]:
    root = widget.get_root()
    return root if isinstance(root, Gtk.Window) else None


# MARK: - Diálogos

def _dialog(parent: Optional[Gtk.Window], width: int = 420) -> tuple[Gtk.Window, Gtk.Box]:
    win = Gtk.Window(modal=True, transient_for=parent, resizable=False, default_width=width)
    win.add_css_class("mn-dialog")
    win.set_titlebar(Gtk.Box(visible=False))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=22, margin_bottom=20,
                  margin_start=24, margin_end=24)
    win.set_child(box)
    esc = Gtk.ShortcutController()
    esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"),
                                      Gtk.CallbackAction.new(lambda *_: (win.close(), True)[1])))
    win.add_controller(esc)
    return win, box


def _title(text: str, subtitle: str = "") -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    t = Gtk.Label(label=text.upper(), xalign=0, wrap=True)
    t.add_css_class("mn-dialog-title")
    box.append(t)
    if subtitle:
        s = Gtk.Label(label=subtitle, xalign=0, wrap=True, max_width_chars=50)
        s.add_css_class("mn-dialog-subtitle")
        box.append(s)
    return box


def _buttons(*buttons: Gtk.Widget) -> Gtk.Box:
    row = Gtk.Box(spacing=8, margin_top=4)
    row.append(hspacer())
    for b in buttons:
        row.append(b)
    return row


def prompt(parent: Optional[Gtk.Window], title: str, ok_label: str, done: Callable[[str], None],
           text: str = "", placeholder: str = "Nombre", subtitle: str = ""):
    """Pide un texto (nueva libreta, renombrar, enlace…)."""
    win, box = _dialog(parent)
    box.append(_title(title, subtitle))
    entry = Gtk.Entry(text=text, placeholder_text=placeholder, activates_default=True)
    box.append(entry)

    def accept():
        value = entry.get_text()
        win.close()
        done(value)

    ok = text_button(ok_label, accept, "mn-primary")
    box.append(_buttons(text_button("Cancelar", win.close, "mn-secondary"), ok))
    win.set_default_widget(ok)
    win.present()
    entry.grab_focus()
    entry.select_region(0, -1)


def confirm(parent: Optional[Gtk.Window], title: str, message: str, ok_label: str, done: Callable[[], None],
            destructive: bool = True):
    win, box = _dialog(parent)
    box.append(_title(title, message))

    def accept():
        win.close()
        done()

    ok = text_button(ok_label, accept, "mn-secondary" if destructive else "mn-primary")
    if destructive:
        ok.add_css_class("destructive")
    cancel = text_button("Cancelar", win.close, "mn-primary" if destructive else "mn-secondary")
    box.append(_buttons(cancel, ok) if destructive else _buttons(cancel, ok))
    win.set_default_widget(cancel if destructive else ok)
    win.present()


def alert(parent: Optional[Gtk.Window], title: str, message: str):
    win, box = _dialog(parent)
    box.append(_title(title, message))
    ok = text_button("Aceptar", win.close, "mn-primary")
    box.append(_buttons(ok))
    win.set_default_widget(ok)
    win.present()


# MARK: - Portapapeles

class AutoCopy:
    """Copia al portapapeles lo que el usuario selecciona y avisa a la barra de estado del editor."""
    listeners: list[Callable[[], None]] = []

    @classmethod
    def copy(cls, text: str, notify: bool = True):
        if not text:
            return
        Gdk.Display.get_default().get_clipboard().set(text)
        if notify:
            for fn in list(cls.listeners):
                fn()


def set_clipboard(text: str):
    Gdk.Display.get_default().get_clipboard().set(text)


# MARK: - Formatos

_WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic"]


def relative_date(ms: int, now: Optional[dt.datetime] = None) -> str:
    """Como en el diseño: hora si es de hoy, «Ayer», día de la semana o «12 oct»."""
    date = dt.datetime.fromtimestamp(ms / 1000)
    now = now or dt.datetime.now()
    days = (now.date() - date.date()).days
    if days == 0:
        return f"{date.hour}:{date.minute:02d}"
    if days == 1:
        return "Ayer"
    if 2 <= days < 7:
        return _WEEKDAYS[date.weekday()]
    s = f"{date.day} {_MONTHS[date.month - 1]}"
    if date.year != now.year:
        s += f" {date.year}"
    return s


def highlight_markup(text: str, query: str) -> str:
    """Texto con las coincidencias de la búsqueda resaltadas en amarillo (marcado de Pango)."""
    terms = [t for t in query.split() if t]
    if not terms:
        return GLib.markup_escape_text(text)
    marks = [False] * len(text)
    for term in terms:
        start = 0
        while True:
            r = find_folded(text, term, start)
            if r is None:
                break
            for k in range(r[0], r[1]):
                marks[k] = True
            start = r[1]
    out, i = [], 0
    while i < len(text):
        j = i
        while j < len(text) and marks[j] == marks[i]:
            j += 1
        chunk = GLib.markup_escape_text(text[i:j])
        out.append(f'<span background="#FFB800" foreground="#000000">{chunk}</span>' if marks[i] else chunk)
        i = j
    return "".join(out)


def hatched_area(spacing: float = 10, height: int = -1) -> Gtk.DrawingArea:
    """Fondo rayado del diseño para imágenes sin cargar."""
    area = Gtk.DrawingArea()
    if height > 0:
        area.set_content_height(height)

    def draw(_area, cr, w, h):
        cr.set_source_rgb(0x12 / 255, 0x12 / 255, 0x12 / 255)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgb(0x1A / 255, 0x1A / 255, 0x1A / 255)
        cr.set_line_width(spacing)
        x = -h
        while x < w:
            cr.move_to(x, h)
            cr.line_to(x + h, 0)
            x += spacing * 2
        cr.stroke()
    area.set_draw_func(draw)
    return area


def gradient_check(checked: bool) -> Gtk.Widget:
    """Casilla de verificación con el degradado del diseño."""
    box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    box.add_css_class("mn-check")
    img = Gtk.Image(icon_name="object-select-symbolic", hexpand=True, halign=Gtk.Align.CENTER)
    box.append(img)
    set_check(box, checked)
    return box


def set_check(box: Gtk.Widget, checked: bool):
    (box.add_css_class if checked else box.remove_css_class)("on")
    child = box.get_first_child()
    if child:
        child.set_opacity(1 if checked else 0)


def ceil(x: float) -> int:
    return int(math.ceil(x))
