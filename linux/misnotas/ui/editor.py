"""Columna del editor: barra de herramientas, título, bloques y pie."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from gi.repository import Gdk, GLib, Gtk, Pango

from ..core.models import Block, Note
from ..state import AppState
from .blocks import BlockRow, ImageBlock, make_block
from .richtext import BlockText, LineField
from .widgets import AutoCopy, hspacer, icon_button, relative_date, set_clipboard, text_button

if TYPE_CHECKING:
    from ..sync import SyncCoordinator


@dataclass
class EditorContext:
    state: AppState
    sync: "SyncCoordinator"


def focused_block_text(window: Optional[Gtk.Window]) -> Optional[BlockText]:
    """El editor de texto con el foco (para aplicar formato)."""
    w = window.get_focus() if window else None
    while w is not None:
        if isinstance(w, BlockText):
            return w
        w = w.get_parent()
    return None


class NotebookPicker(Gtk.MenuButton):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.add_css_class("mn-picker")
        self.set_can_focus(False)
        self.set_focus_on_click(False)
        self.set_has_frame(False)
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image(icon_name="mn-notebook-symbolic", pixel_size=12))
        self.label = Gtk.Label(max_width_chars=22, ellipsize=Pango.EllipsizeMode.END, width_chars=0)
        box.append(self.label)
        chev = Gtk.Image(icon_name="pan-down-symbolic")
        chev.add_css_class("chev")
        box.append(chev)
        self.set_child(box)
        self.popover = Gtk.Popover(has_arrow=False)
        self.popover.add_css_class("mn-popover")
        self.set_popover(self.popover)
        self.note: Optional[Note] = None

    def refresh(self, note: Note):
        self.note = note
        name = self.state.notebook_name(note.notebook_id)
        self.label.set_label(name or "Sin libreta")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, width_request=200)
        for nb in self.state.notebooks:
            row = Gtk.Box(spacing=8)
            row.add_css_class("mn-menu-item")
            check = Gtk.Image(icon_name="object-select-symbolic", pixel_size=12)
            check.set_opacity(1 if nb.id == note.notebook_id else 0)
            row.append(check)
            row.append(Gtk.Label(label=nb.name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            g = Gtk.GestureClick()
            g.connect("released", lambda *_a, id=nb.id: (self.popover.popdown(),
                                                          self.state.move(self.note.id, id)))
            row.add_controller(g)
            box.append(row)
        self.popover.set_child(box)


class EditorView(Gtk.Box):
    def __init__(self, ctx: EditorContext):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.ctx = ctx
        self.state = ctx.state
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.NONE)
        self.append(self.stack)

        # Sin nota.
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER,
                        halign=Gtk.Align.CENTER)
        label = Gtk.Label(label="NINGUNA NOTA SELECCIONADA")
        label.add_css_class("mn-empty-editor")
        empty.append(label)
        b = text_button("Nueva nota", self.state.new_note, "mn-primary")
        b.set_halign(Gtk.Align.CENTER)
        empty.append(b)
        empty_page = Gtk.WindowHandle(child=empty)
        self.stack.add_named(empty_page, "empty")

        # Nota.
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.append(self._toolbar())
        self.banner = self._trash_banner()
        page.append(self.banner)

        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.body.add_css_class("mn-body")
        self.body.set_margin_start(48)
        self.body.set_margin_end(18)
        self.body.set_margin_top(32)
        self.body.set_margin_bottom(64)
        self.title = LineField("Sin título", "mn-title")
        self.title.on_focused = self._title_focused
        self.title.on_change = lambda v: self.note and self.state.update(self.note.id, lambda n: setattr(n, "title", v))
        self.title.on_submit = self._focus_first_block
        self.title.on_move_down = self._focus_first_block
        title_row = Gtk.Box()
        title_row.append(self.title)
        title_row.append(Gtk.Box(width_request=30))
        self.body.append(title_row)
        self.title_row = title_row
        # Ocupa al menos el alto visible: un clic en la zona vacía empieza a escribir.
        self.filler = Gtk.Box(vexpand=True)
        self.body.append(self.filler)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(self.body)
        self.outer = outer
        self.scroller.set_child(outer)
        click = Gtk.GestureClick()
        click.connect("released", self._body_clicked)
        outer.add_controller(click)
        page.append(self.scroller)
        self._setup_select_all_sink()

        page.append(self._footer())
        self.stack.add_named(page, "note")

        self.note: Optional[Note] = None
        self.rows: dict[str, BlockRow] = {}
        self.state.subscribe(self._changed)
        self.state.split_active_text = self._split_active_text
        AutoCopy.listeners.append(self._show_copied)
        self._render()

    # MARK: Construcción

    def _toolbar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=2)
        bar.add_css_class("mn-editor-toolbar")
        s = self.state
        self.format_buttons = [
            icon_button("format-text-bold-symbolic", "Negrita  Ctrl+B", lambda: self.format("bold")),
            icon_button("format-text-italic-symbolic", "Cursiva  Ctrl+I", lambda: self.format("italic")),
            icon_button("format-text-underline-symbolic", "Subrayado  Ctrl+U", lambda: self.format("underline")),
            icon_button("mn-heading-symbolic", "Encabezado  Ctrl+Alt+H", s.toggle_heading),
        ]
        sep = Gtk.Box(valign=Gtk.Align.CENTER)
        sep.add_css_class("mn-toolbar-sep")
        self.insert_buttons = [
            icon_button("view-list-bullet-symbolic", "Lista  Ctrl+Alt+L", self.add_todo),
            icon_button("mn-code-symbolic", "Bloque de código  Ctrl+Alt+C", self.add_code),
            icon_button("mn-link-symbolic", "Enlace  Ctrl+K", self.link),
            icon_button("insert-image-symbolic", "Imagen", self.add_image),
        ]
        for b in self.format_buttons:
            bar.append(b)
        bar.append(sep)
        for b in self.insert_buttons:
            bar.append(b)
        bar.append(hspacer())
        self.picker = NotebookPicker(s)
        bar.append(self.picker)
        self.star = icon_button("non-starred-symbolic", "", lambda: self.note and s.toggle_favorite(self.note.id))
        bar.append(self.star)
        self.trash_button = icon_button("user-trash-symbolic", "", self._trash_clicked)
        bar.append(self.trash_button)
        bar.append(Gtk.WindowControls(side=Gtk.PackType.END, margin_start=6))
        # En ventanas estrechas (p. ej. en mosaico) la barra se desplaza en vez de ensanchar el editor.
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                      vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      child=bar)
        return Gtk.WindowHandle(child=scroller)

    def _trash_banner(self) -> Gtk.Widget:
        box = Gtk.Box(spacing=12)
        box.add_css_class("mn-trash-banner")
        box.append(Gtk.Label(label="Esta nota está en la Papelera.", xalign=0, hexpand=True))
        box.append(text_button("Restaurar", lambda: self.note and self.state.restore(self.note.id),
                               "mn-primary", "compact"))
        box.append(text_button("Eliminar", lambda: self.note and self.state.delete_forever(self.note.id),
                               "mn-secondary", "compact"))
        return box

    def _footer(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=8)
        bar.add_css_class("mn-footer")
        self.footer_left = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        bar.append(self.footer_left)
        self.copied = Gtk.Box(spacing=6, visible=False)
        self.copied.append(Gtk.Image(icon_name="object-select-symbolic", pixel_size=11))
        self.copied.append(Gtk.Label(label="Texto copiado al portapapeles"))
        bar.append(self.copied)
        bar.append(Gtk.Box(hexpand=True))
        self.words = Gtk.Label()
        bar.append(self.words)
        self._copied_timer: Optional[int] = None
        return bar

    def _show_copied(self):
        self.copied.set_visible(True)
        if self._copied_timer:
            GLib.source_remove(self._copied_timer)

        def hide():
            self._copied_timer = None
            self.copied.set_visible(False)
            return False
        self._copied_timer = GLib.timeout_add(2000, hide)

    # MARK: Acciones

    def window(self) -> Optional[Gtk.Window]:
        root = self.get_root()
        return root if isinstance(root, Gtk.Window) else None

    def format(self, name: str):
        t = focused_block_text(self.window())
        if t:
            t.toggle(name)

    def link(self):
        t = focused_block_text(self.window())
        if t:
            t.edit_link()

    def add_todo(self):
        b = Block.todo()
        self.state.insert_block(b, f"todo:{b.id}:0")

    def add_code(self):
        b = Block.code()
        self.state.insert_block(b, "block:" + b.id)

    def add_image(self):
        if not self.note or self.note.is_trashed:
            return
        dialog = Gtk.FileDialog(title="Elegir imagen", modal=True)
        f = Gtk.FileFilter(name="Imágenes")
        f.add_mime_type("image/*")
        from gi.repository import Gio
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.set_default_filter(f)
        # Recuerda el bloque activo: el diálogo se lleva el foco.
        active = self.state.active_block_id

        def done(dlg, result):
            try:
                file = dlg.open_finish(result)
            except GLib.Error:
                return
            if file and file.get_path():
                self.state.active_block_id = active
                self.state.add_image(file.get_path())
        dialog.open(self.window(), None, done)

    def _trash_clicked(self):
        if not self.note:
            return
        if self.note.is_trashed:
            self.state.delete_forever(self.note.id)
        else:
            self.state.trash(self.note.id)

    def _split_active_text(self):
        t = focused_block_text(self.window())
        return t.split_at_caret() if t else None

    def _title_focused(self):
        self.state.clear_all_selected()
        if self.note and self.state.focus and self.state.focus.note_id == self.note.id and self.state.focus.key == "title":
            self.state.focus = None

    def _focus_first_block(self):
        if self.note:
            self.state.move_focus(None, False, self.note.id)

    def _body_clicked(self, gesture, n, x, y):
        """Clic en la zona vacía del editor: cursor al final del último bloque."""
        if not self.note:
            return
        picked = self.outer.pick(x, y, Gtk.PickFlags.DEFAULT)
        if picked in (self.outer, self.body, self.filler):
            self.state.focus_end(self.note.id)

    def flush_all(self):
        self.title.flush()
        for row in self.rows.values():
            row.flush()

    # MARK: Selección de todos los bloques

    def _setup_select_all_sink(self):
        """Recibe el teclado mientras todos los bloques están seleccionados: copiar, cortar, borrar
        o escribir encima. Cualquier otra tecla de movimiento o clic quita la selección."""
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._sink_key)
        self.body.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self.state.clear_all_selected())
        self.body.add_controller(focus)

    def _sink_key(self, ctrl, keyval, keycode, state):
        if not self.note or self.state.all_selected_note_id != self.note.id:
            return False
        nid = self.note.id
        ctrl_down = state & Gdk.ModifierType.CONTROL_MASK
        if ctrl_down and keyval in (Gdk.KEY_c, Gdk.KEY_C):
            set_clipboard(self.state.plain_text_of(nid))
            return True
        if ctrl_down and keyval in (Gdk.KEY_x, Gdk.KEY_X):
            set_clipboard(self.state.plain_text_of(nid))
            self.state.replace_all_blocks(nid)
            return True
        if ctrl_down and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            return True
        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            self.state.replace_all_blocks(nid)
            return True
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Return):
            self.state.clear_all_selected()
            win = self.window()
            if win:
                win.set_focus(None)
            return True
        ch = Gdk.keyval_to_unicode(keyval)
        if ch and not ctrl_down and not (state & Gdk.ModifierType.ALT_MASK) and chr(ch).isprintable():
            self.state.replace_all_blocks(nid, chr(ch))
            return True
        return True

    # MARK: Render

    def _changed(self, topics: set):
        if topics & {"selection", "notes", "editor", "notebooks", "nav"}:
            self._render()
        if "attachments" in topics:
            for row in self.rows.values():
                if isinstance(row, ImageBlock):
                    row.refresh_attachments()
        if "allselected" in topics:
            self._render_all_selected()
        if "focus" in topics or topics & {"selection", "editor"}:
            # Tras la maquetación: los bloques recién creados ya tienen tamaño.
            GLib.idle_add(self._apply_focus)

    def _render(self):
        note = self.state.selected_note
        if note is None:
            if self.note is not None:
                self.flush_all()
                self._clear_rows()
            self.note = None
            self.stack.set_visible_child_name("empty")
            return
        self.stack.set_visible_child_name("note")
        if self.note is None or self.note.id != note.id:
            if self.note is not None:
                self.flush_all()
            self._clear_rows()
            self.title.last_value = None  # fuerza la recarga
            self.scroller.get_vadjustment().set_value(0)
        self.note = note
        trashed = note.is_trashed

        # Barra.
        for b in self.format_buttons + self.insert_buttons:
            b.set_sensitive(not trashed)
        self.picker.set_sensitive(not trashed)
        self.star.set_sensitive(not trashed)
        self.star.set_icon_name("starred-symbolic" if note.favorite else "non-starred-symbolic")
        (self.star.add_css_class if note.favorite else self.star.remove_css_class)("favorite")
        self.star.set_tooltip_text("Quitar de favoritas  Ctrl+Mayús+F" if note.favorite
                                   else "Añadir a favoritas  Ctrl+Mayús+F")
        self.trash_button.set_tooltip_text("Eliminar definitivamente" if trashed else "Mover a la Papelera  Ctrl+Supr")
        self.picker.refresh(note)
        self.banner.set_visible(trashed)
        self.body.set_sensitive(not trashed)

        # Título y bloques.
        self.title.set_value(note.title)
        prev: Gtk.Widget = self.title_row
        seen = set()
        for block in note.blocks:
            seen.add(block.id)
            row = self.rows.get(block.id)
            if row is not None and not row.matches(block):
                self.body.remove(row)
                row = None
            if row is None:
                row = make_block(self.ctx, note, block)
                self.rows[block.id] = row
                self.body.insert_child_after(row, prev)
            else:
                row.update(note, block)
                if row.get_prev_sibling() is not prev:
                    self.body.reorder_child_after(row, prev)
            prev = row
        for id in [id for id in self.rows if id not in seen]:
            self.body.remove(self.rows.pop(id))

        # Pie.
        words = note.word_count
        nb = self.state.notebook_name(note.notebook_id)
        self.footer_left.set_label((nb + " · " if nb else "") + "Editada " + relative_date(note.updated_at).lower())
        self.words.set_label("1 palabra" if words == 1 else f"{words} palabras")
        self._render_all_selected()

    def _clear_rows(self):
        for row in self.rows.values():
            self.body.remove(row)
        self.rows = {}

    def _render_all_selected(self):
        on = self.note is not None and self.state.all_selected_note_id == self.note.id
        (self.body.add_css_class if on else self.body.remove_css_class)("all-selected")
        self.body.set_focusable(on)
        if on and not self.body.has_focus():
            self.body.grab_focus()

    def _apply_focus(self, attempt: int = 0):
        """Da el foco al control pedido en `state.focus`. Un bloque recién creado aún no está en pantalla:
        se reintenta en el siguiente fotograma hasta que lo esté."""
        target = self.state.focus
        if target is None or self.note is None or target.note_id != self.note.id:
            return False
        if target.key == "title":
            widgets = [self.title]
        else:
            widgets = [row for row in self.rows.values() if row.handles_focus(target.key)]
        if not widgets:
            return False
        widget = widgets[0]
        if not widget.get_mapped() and attempt < 30:
            GLib.timeout_add(16, self._apply_focus, attempt + 1)
            return False
        if widget is self.title:
            self.title.grab(target.at_start)
        else:
            widget.focus(target.key, target.at_start)
        if self.state.focus is target:
            self.state.focus = None
        return False
