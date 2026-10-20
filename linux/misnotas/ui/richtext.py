"""Controles de texto del editor.

- `BlockText`: GtkTextView multilínea que crece con su contenido. En modo enriquecido edita el HTML
  limitado de los párrafos (negrita, cursiva, subrayado, enlaces); en modo plano, texto sin formato (código).
- `LineField`: GtkText de una línea con control de Intro, Retroceso en vacío, flechas y Esc
  (título, elementos de lista, enlaces, pies de foto).
"""
from __future__ import annotations

from typing import Callable, Optional

from gi.repository import Gdk, GLib, Gtk, Pango

from ..core import inline_html
from ..core.inline_html import Run, Style
from .theme import ORANGE
from .widgets import AutoCopy, prompt, window_of

SAVE_DELAY_MS = 300
_MODS = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK
_LINK = "link:"


def open_url(widget: Gtk.Widget, url: str):
    url = url.strip()
    if not url:
        return
    if "://" not in url and not url.lower().startswith("mailto:"):
        url = "https://" + url
    Gtk.UriLauncher.new(url).launch(window_of(widget), None, None, None)


class BlockText(Gtk.Overlay):
    def __init__(self, rich: bool = True, heading: bool = False, placeholder: str = ""):
        super().__init__()
        self.rich = rich
        self.heading = heading
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, accepts_tab=not rich)
        self.view.add_css_class("mn-text")
        if heading:
            self.view.add_css_class("heading")
        if not rich:
            self.view.add_css_class("code")
            self.view.set_monospace(True)
            self.view.set_pixels_inside_wrap(6)
            self.view.set_pixels_below_lines(6)
        elif not heading:
            self.view.set_pixels_inside_wrap(6)
            self.view.set_pixels_below_lines(6)
        self.set_child(self.view)
        # La vista crece con su texto y nunca se desplaza por dentro (el desplazamiento es del editor). Sin esto,
        # al recibir el foco antes de tener tamaño, GtkTextView se desplaza hacia el cursor y el texto queda oculto.
        for setter in (self.view.set_vadjustment, self.view.set_hadjustment):
            adj = Gtk.Adjustment()
            adj.connect("value-changed", lambda a: a.get_value() != 0 and a.set_value(0))
            setter(adj)
        self.buffer = self.view.get_buffer()
        self.buffer.set_enable_undo(True)

        self.placeholder = Gtk.Label(label=placeholder, xalign=0, halign=Gtk.Align.START, valign=Gtk.Align.START,
                                     can_target=False, visible=False)
        self.placeholder.add_css_class("mn-placeholder")
        self.add_overlay(self.placeholder)

        tags = self.buffer.get_tag_table()
        self.tag_bold = Gtk.TextTag(name="bold", weight=Pango.Weight.BOLD)
        self.tag_italic = Gtk.TextTag(name="italic", style=Pango.Style.ITALIC)
        self.tag_underline = Gtk.TextTag(name="underline", underline=Pango.Underline.SINGLE)
        for t in (self.tag_bold, self.tag_italic, self.tag_underline):
            tags.add(t)

        # Callbacks (los asigna el bloque).
        self.on_change: Callable[[str], None] = lambda v: None
        self.on_focused: Callable[[], None] = lambda: None
        self.on_delete_empty: Optional[Callable[[], None]] = None
        # Intro tras una línea `---`: recibe el HTML de antes y de después de esa línea.
        self.on_divider: Optional[Callable[[str, str], None]] = None
        # ↑ en la primera línea / ↓ en la última: salir al bloque anterior o siguiente.
        self.on_move_up: Optional[Callable[[], None]] = None
        self.on_move_down: Optional[Callable[[], None]] = None

        self.last_value = ""
        self._loading = False
        self._pending: Optional[int] = None
        # Formato para lo próximo que se escriba (Ctrl+B sin selección). None = el del texto anterior.
        self._typing: Optional[Style] = None
        self._link_click: Optional[str] = None

        self.buffer.connect("changed", self._changed)
        self.buffer.connect("apply-tag", lambda *a: self._changed())
        self.buffer.connect("remove-tag", lambda *a: self._changed())
        self.buffer.connect_after("insert-text", self._after_insert)
        self.buffer.connect("mark-set", self._mark_set)

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self._focus_enter)
        focus.connect("leave", self._focus_leave)
        self.view.add_controller(focus)

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key_pressed)
        keys.connect("key-released", self._key_released)
        self.view.add_controller(keys)

        # Lo seleccionado con el ratón se copia solo al portapapeles.
        legacy = Gtk.EventControllerLegacy(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        legacy.connect("event", self._legacy_event)
        self.view.add_controller(legacy)

        # Clic en un enlace del texto: se abre (Ctrl+clic para editarlo).
        click = Gtk.GestureClick(button=1, propagation_phase=Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._click_pressed)
        click.connect("released", self._click_released)
        self.view.add_controller(click)
        self._click = click

        self.connect("unmap", lambda *_: self.flush())

    # MARK: Contenido

    def set_value(self, value: str):
        """Solo se recarga si el valor cambió desde fuera (sincronización, cambio de nota) y no se está escribiendo."""
        if value != self.last_value and not self.view.has_focus():
            self.load(value)

    def load(self, value: str):
        self._loading = True
        self.buffer.begin_irreversible_action()
        self.buffer.set_text("")
        if self.rich:
            end = self.buffer.get_end_iter()
            for run in inline_html.parse(value):
                self.buffer.insert_with_tags(end, run.text, *self._tags_for(run.style))
                end = self.buffer.get_end_iter()
        else:
            self.buffer.set_text(value)
        self.buffer.end_irreversible_action()
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self._loading = False
        self.last_value = value
        self._typing = None
        self._update_placeholder()

    def value(self) -> str:
        start, end = self.buffer.get_bounds()
        return self.html(start, end) if self.rich else self.buffer.get_text(start, end, True)

    def html(self, start: Gtk.TextIter, end: Gtk.TextIter) -> str:
        runs: list[Run] = []
        it = start.copy()
        while it.compare(end) < 0:
            nxt = it.copy()
            if not nxt.forward_to_tag_toggle(None) or nxt.compare(end) > 0:
                nxt = end.copy()
            runs.append(Run(self.buffer.get_text(it, nxt, True), self._style_at(it)))
            it = nxt
        return inline_html.html_from_runs(runs)

    def is_empty(self) -> bool:
        return self.buffer.get_char_count() == 0

    def _style_at(self, it: Gtk.TextIter) -> Style:
        bold = italic = underline = False
        link = None
        for tag in it.get_tags():
            name = tag.props.name or ""
            if name == "bold":
                bold = True
            elif name == "italic":
                italic = True
            elif name == "underline":
                underline = True
            elif name.startswith(_LINK):
                link = name[len(_LINK):]
        return Style(bold, italic, underline, link)

    def _tags_for(self, style: Style) -> list[Gtk.TextTag]:
        out = []
        if style.bold:
            out.append(self.tag_bold)
        if style.italic:
            out.append(self.tag_italic)
        if style.underline:
            out.append(self.tag_underline)
        if style.link:
            out.append(self._link_tag(style.link))
        return out

    def _link_tag(self, url: str) -> Gtk.TextTag:
        table = self.buffer.get_tag_table()
        tag = table.lookup(_LINK + url)
        if tag is None:
            tag = Gtk.TextTag(name=_LINK + url, foreground=ORANGE, underline=Pango.Underline.SINGLE)
            table.add(tag)
        return tag

    def _apply_style(self, start: Gtk.TextIter, end: Gtk.TextIter, style: Style):
        self.buffer.remove_all_tags(start, end)
        for tag in self._tags_for(style):
            self.buffer.apply_tag(tag, start, end)

    # MARK: Guardado agrupado

    def _changed(self, *_):
        """El guardado (HTML, base de datos, lista de notas) se agrupa: hacerlo en cada pulsación es costoso."""
        if self._loading:
            return
        self._update_placeholder()
        if self._pending is not None:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(SAVE_DELAY_MS, self._fire)

    def _fire(self):
        self._pending = None
        self.flush()
        return False

    def flush(self):
        if self._pending is not None:
            GLib.source_remove(self._pending)
            self._pending = None
        value = self.value()
        if value == self.last_value:
            return
        self.last_value = value
        self.on_change(value)

    # MARK: Formato al escribir

    def _after_insert(self, buffer, location, text, length):
        """GtkTextBuffer no extiende el formato al escribir: el texto nuevo toma el del carácter anterior
        (o el pedido con Ctrl+B/I/U), como en macOS."""
        if self._loading or not self.rich:
            return
        start = location.copy()
        start.backward_chars(len(text))
        style = self._typing
        if style is None:
            if start.get_offset() > 0:
                prev = start.copy()
                prev.backward_char()
                style = self._style_at(prev)
                # Un enlace solo se extiende si se escribe dentro de él.
                if style.link and self._style_at(location).link != style.link:
                    style = Style(style.bold, style.italic, style.underline, None)
            else:
                after = self._style_at(location) if not location.is_end() else Style()
                style = Style(after.bold, after.italic, after.underline, None)
        mark = self.buffer.create_mark(None, location, False)
        self._apply_style(start, location, style)
        location.assign(self.buffer.get_iter_at_mark(mark))
        self.buffer.delete_mark(mark)

    def _mark_set(self, buffer, it, mark):
        if mark == buffer.get_insert() and not self._loading:
            self._typing = None

    # MARK: Foco y teclado

    def _focus_enter(self, *_):
        self._update_placeholder()
        self.on_focused()

    def _focus_leave(self, *_):
        self._update_placeholder()
        self.flush()

    def _update_placeholder(self):
        self.placeholder.set_visible(bool(self.placeholder.get_label()) and self.is_empty() and self.view.has_focus())

    def grab(self, at_start: bool = False):
        self.view.grab_focus()
        it = self.buffer.get_start_iter() if at_start else self.buffer.get_end_iter()
        self.buffer.place_cursor(it)

    def _key_pressed(self, ctrl, keyval, keycode, state):
        mods = state & _MODS
        has_sel = self.buffer.get_has_selection()
        if keyval == Gdk.KEY_BackSpace and not mods and self.is_empty() and self.on_delete_empty:
            self.on_delete_empty()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not mods and self.on_divider and self.rich and not has_sel:
            if self._try_divider():
                return True
        if keyval == Gdk.KEY_Up and not mods and not has_sel and self.on_move_up and self._on_first_line():
            self.flush()
            self.on_move_up()
            return True
        if keyval == Gdk.KEY_Down and not mods and not has_sel and self.on_move_down and self._on_last_line():
            self.flush()
            self.on_move_down()
            return True
        return False

    def _key_released(self, ctrl, keyval, keycode, state):
        # Selección con el teclado (Mayús + flechas).
        if state & Gdk.ModifierType.SHIFT_MASK and self.buffer.get_has_selection():
            self._copy_selection()

    def _legacy_event(self, ctrl, event):
        event = event or ctrl.get_current_event()
        if event is not None and event.get_event_type() == Gdk.EventType.BUTTON_RELEASE:
            GLib.idle_add(lambda: (self._copy_selection(), False)[1])
        return False

    def _copy_selection(self):
        bounds = self.buffer.get_selection_bounds()
        if bounds:
            AutoCopy.copy(self.buffer.get_text(bounds[0], bounds[1], True))

    def _cursor(self) -> Gtk.TextIter:
        return self.buffer.get_iter_at_mark(self.buffer.get_insert())

    def _on_first_line(self) -> bool:
        return self.view.get_iter_location(self._cursor()).y <= self.view.get_iter_location(self.buffer.get_start_iter()).y

    def _on_last_line(self) -> bool:
        return self.view.get_iter_location(self._cursor()).y >= self.view.get_iter_location(self.buffer.get_end_iter()).y

    def _try_divider(self) -> bool:
        """Intro al final de una línea que solo contiene `---` la convierte en una línea horizontal,
        como en Evernote. El texto de antes y de después se queda en párrafos aparte."""
        cursor = self._cursor()
        line_start = cursor.copy()
        line_start.set_line_offset(0)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        if not cursor.equal(line_end) or self.buffer.get_text(line_start, line_end, True).strip() != "---":
            return False
        before_end = line_start.copy()
        if before_end.get_offset() > 0:
            before_end.backward_char()  # sin el salto de línea anterior
        before = self.html(self.buffer.get_start_iter(), before_end)
        after_start = line_end.copy()
        after_start.forward_char()
        after = self.html(after_start, self.buffer.get_end_iter()) if not line_end.is_end() else ""
        # Suelta el foco para que el bloque recargue su texto (no se recarga mientras se escribe).
        self._release_focus()
        self.on_divider(before, after)
        return True

    def _release_focus(self):
        win = window_of(self)
        if win:
            win.set_focus(None)
        self.flush()

    def split_at_caret(self) -> Optional[tuple[str, str]]:
        """Parte el texto por el cursor (o la selección) para insertar un bloque en medio. Quita los saltos de
        línea pegados al corte y suelta el foco para que el bloque recargue su contenido. Solo en texto enriquecido."""
        if not self.rich:
            return None
        bounds = self.buffer.get_selection_bounds()
        start, end = bounds if bounds else (self._cursor(), self._cursor())
        cut_end = start.copy()
        while cut_end.get_offset() > 0:
            prev = cut_end.copy()
            prev.backward_char()
            if prev.get_char() != "\n":
                break
            cut_end = prev
        cut_start = end.copy()
        while not cut_start.is_end() and cut_start.get_char() == "\n":
            cut_start.forward_char()
        before = self.html(self.buffer.get_start_iter(), cut_end)
        after = self.html(cut_start, self.buffer.get_end_iter())
        self._release_focus()
        return before, after

    # MARK: Enlaces en el texto

    def _link_at(self, x: float, y: float) -> Optional[str]:
        bx, by = self.view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        ok, it = self.view.get_iter_at_location(bx, by)
        if not ok:
            return None
        return self._style_at(it).link

    def _click_pressed(self, gesture, n, x, y):
        self._link_click = None
        state = gesture.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK or not self.rich:
            return
        link = self._link_at(x, y)
        if link:
            self._link_click = link
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _click_released(self, gesture, n, x, y):
        if self._link_click:
            link, self._link_click = self._link_click, None
            open_url(self, link)

    # MARK: Formato

    def toggle(self, name: str):
        """Negrita/cursiva/subrayado sobre la selección; sin selección, para lo próximo que se escriba."""
        if not self.rich:
            return
        tag = {"bold": self.tag_bold, "italic": self.tag_italic, "underline": self.tag_underline}[name]
        bounds = self.buffer.get_selection_bounds()
        if not bounds:
            cur = self._typing
            if cur is None:
                it = self._cursor()
                if it.get_offset() > 0:
                    it.backward_char()
                cur = self._style_at(it) if self.buffer.get_char_count() else Style()
                cur = Style(cur.bold, cur.italic, cur.underline, None)
            on = not getattr(cur, name)
            self._typing = Style(**{**cur.__dict__, name: on})
            return
        start, end = bounds
        it = start.copy()
        all_on = True
        while it.compare(end) < 0:
            if not it.has_tag(tag):
                all_on = False
                break
            it.forward_char()
        self.buffer.begin_user_action()
        if all_on:
            self.buffer.remove_tag(tag, start, end)
        else:
            self.buffer.apply_tag(tag, start, end)
        self.buffer.end_user_action()

    def edit_link(self):
        """Enlace dentro del texto: convierte la selección en enlace (o edita el enlace bajo el cursor).
        Con una dirección vacía quita el enlace."""
        if not self.rich:
            return
        bounds = self.buffer.get_selection_bounds()
        start, end = bounds if bounds else (self._cursor(), self._cursor())
        probe = start.copy()
        if not bounds and probe.get_offset() > 0:
            probe.backward_char()
        current = self._style_at(probe).link if self.buffer.get_char_count() else None
        if current and not bounds:
            tag = self._link_tag(current)
            start, end = probe.copy(), probe.copy()
            if not start.starts_tag(tag):
                start.backward_to_tag_toggle(tag)
            end.forward_to_tag_toggle(tag)
        selected_text = self.buffer.get_text(start, end, True)
        m_start = self.buffer.create_mark(None, start, True)
        m_end = self.buffer.create_mark(None, end, False)
        subtitle = (f"Dirección para «{selected_text[:40]}»" if selected_text
                    else "Dirección del enlace (se insertará como texto)")

        def done(address: str):
            self.view.grab_focus()
            s = self.buffer.get_iter_at_mark(m_start)
            e = self.buffer.get_iter_at_mark(m_end)
            self.buffer.delete_mark(m_start)
            self.buffer.delete_mark(m_end)
            address = address.strip()
            if address and "://" not in address and not address.lower().startswith("mailto:"):
                address = "https://" + address
            if address and any(ch.isspace() for ch in address):
                self.view.error_bell()
                return
            self.buffer.begin_user_action()
            if s.equal(e):
                # Sin selección: se inserta la propia dirección como texto del enlace.
                if not address:
                    self.buffer.end_user_action()
                    return
                offset = s.get_offset()
                self._loading = True  # sin heredar formato
                self.buffer.insert(s, address)
                self._loading = False
                s = self.buffer.get_iter_at_offset(offset)
                e = self.buffer.get_iter_at_offset(offset + len(address))
            for tag in self._link_tags_in(s, e):
                self.buffer.remove_tag(tag, s, e)
            if address:
                self.buffer.apply_tag(self._link_tag(address), s, e)
            self.buffer.end_user_action()
            self.buffer.place_cursor(e)
            self._typing = None
            self._changed()

        prompt(window_of(self), "Editar enlace" if current else "Añadir enlace", "Aceptar", done,
               text=current or "", placeholder="https://…", subtitle=subtitle)

    def _link_tags_in(self, start: Gtk.TextIter, end: Gtk.TextIter) -> list[Gtk.TextTag]:
        found = {}
        it = start.copy()
        while True:
            for tag in it.get_tags():
                if (tag.props.name or "").startswith(_LINK):
                    found[tag.props.name] = tag
            if not it.forward_to_tag_toggle(None) or it.compare(end) >= 0:
                break
        return list(found.values())


class LineField(Gtk.Text):
    """Campo de una línea con control de Intro, Retroceso en vacío, flechas y Esc."""

    def __init__(self, placeholder: str = "", *classes: str):
        super().__init__(placeholder_text=placeholder, hexpand=True)
        for c in classes:
            self.add_css_class(c)
        self.on_change: Callable[[str], None] = lambda v: None
        self.on_focused: Callable[[], None] = lambda: None
        self.on_submit: Optional[Callable[[], None]] = None
        self.on_delete_empty: Optional[Callable[[], None]] = None
        self.on_escape: Optional[Callable[[], None]] = None
        self.on_move_up: Optional[Callable[[], None]] = None
        self.on_move_down: Optional[Callable[[], None]] = None
        self.last_value = ""
        self._loading = False
        self._pending: Optional[int] = None

        self.connect("changed", self._changed)
        self.connect("activate", self._activate)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: self.on_focused())
        focus.connect("leave", self._focus_leave)
        self.add_controller(focus)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key_pressed)
        keys.connect("key-released", self._key_released)
        self.add_controller(keys)
        legacy = Gtk.EventControllerLegacy(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        legacy.connect("event", self._legacy_event)
        self.add_controller(legacy)
        self.connect("unmap", lambda *_: self.flush())

    def _focus_leave(self, *_):
        # Sin foco no se muestra la selección (GtkText la conservaría resaltada).
        self.select_region(0, 0)
        self.flush()

    def set_value(self, value: str):
        if value == self.last_value or self.has_focus():
            return
        self._loading = True
        self.set_text(value)
        self._loading = False
        self.last_value = value

    def _changed(self, *_):
        if self._loading:
            return
        if self._pending is not None:
            GLib.source_remove(self._pending)
        self._pending = GLib.timeout_add(SAVE_DELAY_MS, self._fire)

    def _fire(self):
        self._pending = None
        self.flush()
        return False

    def flush(self):
        if self._pending is not None:
            GLib.source_remove(self._pending)
            self._pending = None
        value = self.get_text()
        if value == self.last_value:
            return
        self.last_value = value
        self.on_change(value)

    def detach(self):
        """Desconecta el campo antes de destruirlo (sus índices ya no son válidos): descarta lo pendiente."""
        if self._pending is not None:
            GLib.source_remove(self._pending)
            self._pending = None
        self.last_value = self.get_text()
        self.on_change = lambda v: None

    def _activate(self, *_):
        if self.on_submit:
            self.flush()
            self.on_submit()

    def grab(self, at_start: bool = False):
        self.grab_focus_without_selecting()
        self.set_position(0 if at_start else -1)

    def _key_pressed(self, ctrl, keyval, keycode, state):
        if state & _MODS:
            return False
        if keyval == Gdk.KEY_BackSpace and not self.get_text() and self.on_delete_empty:
            self.flush()
            self.on_delete_empty()
            return True
        if keyval == Gdk.KEY_Up and self.on_move_up:
            self.flush()
            self.on_move_up()
            return True
        if keyval == Gdk.KEY_Down and self.on_move_down:
            self.flush()
            self.on_move_down()
            return True
        if keyval == Gdk.KEY_Escape and self.on_escape:
            self.flush()
            self.on_escape()
            return True
        return False

    def _key_released(self, ctrl, keyval, keycode, state):
        if state & Gdk.ModifierType.SHIFT_MASK:
            self._copy_selection()

    def _legacy_event(self, ctrl, event):
        event = event or ctrl.get_current_event()
        if event is not None and event.get_event_type() == Gdk.EventType.BUTTON_RELEASE:
            GLib.idle_add(lambda: (self._copy_selection(), False)[1])
        return False

    def _copy_selection(self):
        ok, start, end = self.get_selection_bounds()
        if ok and end > start:
            AutoCopy.copy(self.get_text()[start:end])

    def all_selected(self) -> bool:
        ok, start, end = self.get_selection_bounds()
        text = self.get_text()
        return not text or (ok and start == 0 and end == len(text))
