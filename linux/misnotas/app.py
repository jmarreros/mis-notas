"""Aplicación GTK 4: ventana principal, acciones y atajos de teclado."""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .core.database import AppDatabase, NotesRepository  # noqa: E402
from .platform import APP_ID, ATTACHMENTS_DIR, DATA_DIR  # noqa: E402
from .state import AppState  # noqa: E402
from .sync import SyncCoordinator  # noqa: E402
from .ui import theme  # noqa: E402
from .ui.blocks import DividerBlock  # noqa: E402
from .ui.editor import EditorContext, EditorView, focused_block_text  # noqa: E402
from .ui.importer import ImportWindow  # noqa: E402
from .ui.notelist import NoteListView  # noqa: E402
from .ui.richtext import LineField  # noqa: E402
from .ui.settings import SettingsWindow  # noqa: E402
from .ui.sidebar import Sidebar  # noqa: E402
from .ui.widgets import alert  # noqa: E402

# Atajos: los de macOS con Ctrl en lugar de ⌘.
ACCELS = {
    "win.new-note": ["<Control>n"],
    "win.import": ["<Control><Shift>i"],
    "win.search": ["<Control>f"],
    "win.bold": ["<Control>b"],
    "win.italic": ["<Control>i"],
    "win.underline": ["<Control>u"],
    "win.heading": ["<Control><Alt>h"],
    "win.list": ["<Control><Alt>l"],
    "win.code": ["<Control><Alt>c"],
    "win.link": ["<Control>k"],
    "win.image": ["<Control><Alt>i"],
    "win.trash": ["<Control>Delete"],
    "win.favorite": ["<Control><Shift>f"],
    "win.sidebar": ["F9", "<Control><Shift>s"],
    "win.sync": ["<Control>r"],
    "win.settings": ["<Control>comma"],
    "app.quit": ["<Control>q"],
}


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "MisNotasApp"):
        super().__init__(application=app, title="Mis Notas", default_width=1320, default_height=820)
        self.add_css_class("mn-window")
        self.set_size_request(900, 560)
        self.set_icon_name(APP_ID)
        # Sin barra de título: las barras de cada columna permiten arrastrar la ventana.
        self.set_titlebar(Gtk.Box(visible=False))
        self.state = app.state
        self.sync = app.sync

        root = Gtk.Box()
        self.sidebar = Sidebar(self.state, self.sync, self.open_settings)
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT, transition_duration=180,
                                     reveal_child=self.state.sidebar_open, child=self.sidebar)
        self.revealer.set_hexpand(False)
        root.append(self.revealer)
        self.notelist = NoteListView(self.state)
        self.notelist.set_hexpand(False)
        root.append(self.notelist)
        self.editor = EditorView(EditorContext(self.state, self.sync))
        root.append(self.editor)
        self.set_child(root)

        self.state.subscribe(self._changed)
        self.state.on_error = lambda msg: alert(self, "Error", msg)
        self._install_actions()

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key_capture)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: (self.editor.flush_all(), False)[1])

    def _changed(self, topics: set):
        if "sidebar" in topics:
            self.revealer.set_reveal_child(self.state.sidebar_open)

    # MARK: Acciones

    def _install_actions(self):
        s = self.state
        simple = {
            "new-note": s.new_note,
            "import": self.open_import,
            "search": self.notelist.focus_search,
            "bold": lambda: self.editor.format("bold"),
            "italic": lambda: self.editor.format("italic"),
            "underline": lambda: self.editor.format("underline"),
            "heading": s.toggle_heading,
            "list": self.editor.add_todo,
            "code": self.editor.add_code,
            "link": self.editor.link,
            "image": self.editor.add_image,
            "trash": lambda: s.selected_id and s.trash(s.selected_id),
            "favorite": lambda: s.selected_id and s.toggle_favorite(s.selected_id),
            "sidebar": lambda: s.set_sidebar_open(not s.sidebar_open),
            "sync": self.sync.sync_now,
            "settings": self.open_settings,
            "empty-trash": s.empty_trash,
        }
        for name, fn in simple.items():
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda _a, _p, fn=fn: fn())
            self.add_action(a)

        def note_move(arg: str):
            note_id, nb_id = arg.split("|", 1)
            ids = [i for i in s.drag_payload(note_id).split("\n") if i]
            if len(ids) > 1:
                s.move_many(ids, nb_id)
            else:
                s.move(note_id, nb_id)

        def block_heading(block_id: str):
            if s.selected_id:
                s.update_block(s.selected_id, block_id, lambda b: setattr(b, "type", "p" if b.type == "h" else "h"))

        with_arg = {
            "note-restore": s.restore,
            "note-delete": s.delete_forever,
            "note-favorite": s.toggle_favorite,
            "note-trash": s.trash,
            "note-move": note_move,
            "notebook-rename": self.sidebar.rename_notebook,
            "notebook-delete": self.sidebar.delete_notebook,
            "block-heading": block_heading,
            "block-remove": lambda block_id: s.selected_id and s.remove_block(block_id, s.selected_id),
        }
        for name, fn in with_arg.items():
            a = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            a.connect("activate", lambda _a, p, fn=fn: fn(p.get_string()))
            self.add_action(a)

    def open_settings(self):
        SettingsWindow(self, self.sync).present()

    def open_import(self):
        ImportWindow(self, self.state).present()

    # MARK: Teclado global

    def _key_capture(self, ctrl, keyval, keycode, state):
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK)
        focus = self.get_focus()
        if mods == Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            return self._select_all(focus)
        if mods == Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK:
            # Ctrl+Mayús se resuelve aquí: según el teclado, GTK recibe la letra en minúscula o mayúscula.
            action = {Gdk.KEY_i: "import", Gdk.KEY_f: "favorite", Gdk.KEY_s: "sidebar"}.get(Gdk.keyval_to_lower(keyval))
            if action:
                self.activate_action("win." + action, None)
                return True
        if keyval in (Gdk.KEY_z, Gdk.KEY_Z) and mods & Gdk.ModifierType.CONTROL_MASK:
            redo = bool(mods & Gdk.ModifierType.SHIFT_MASK)
            return self._undo(focus, redo)
        return False

    def _select_all(self, focus) -> bool:
        """Ctrl+A: si el bloque con el foco ya está seleccionado entero (o vacío), selecciona todos los bloques
        de la nota. Cada bloque es un campo aparte, así que no hay una selección nativa común."""
        text = focused_block_text(self)
        whole = False
        if text is not None:
            b = text.buffer
            bounds = b.get_selection_bounds()
            whole = b.get_char_count() == 0 or (bool(bounds) and bounds[0].is_start() and bounds[1].is_end())
        elif isinstance(focus, LineField):
            whole = focus.all_selected()
        elif self._in_divider(focus):
            whole = True
        else:
            return False
        if not whole:
            return False
        self.state.select_all_blocks()
        return True

    @staticmethod
    def _in_divider(w) -> bool:
        while w is not None:
            if isinstance(w, DividerBlock):
                return True
            w = w.get_parent()
        return False

    def _undo(self, focus, redo: bool) -> bool:
        """Ctrl+Z deshace primero el texto del campo con el foco; si no queda nada, los cambios de bloques."""
        text = focused_block_text(self)
        if text is not None:
            b = text.buffer
            if (b.get_can_redo() if redo else b.get_can_undo()):
                return False
        elif isinstance(focus, Gtk.Text):
            return False
        if redo:
            self.state.redo()
        elif self.state.can_undo():
            self.state.undo()
        return True


class MisNotasApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.state: AppState
        self.sync: SyncCoordinator
        self.window: MainWindow | None = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_application_name("Mis Notas")
        theme.install(Gdk.Display.get_default())
        try:
            db = AppDatabase.on_disk(DATA_DIR)
        except Exception as e:  # noqa: BLE001
            print(f"No se pudo abrir la base de datos local: {e}", file=sys.stderr)
            raise
        self.state = AppState(NotesRepository(db), ATTACHMENTS_DIR)
        self.state.schedule = lambda fn: GLib.idle_add(fn)
        self.sync = SyncCoordinator(self.state)
        quit = Gio.SimpleAction.new("quit", None)
        quit.connect("activate", lambda *_: self._quit())
        self.add_action(quit)
        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

    def _quit(self):
        if self.window:
            self.window.editor.flush_all()
        self.quit()

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def main() -> int:
    # Todas las ventanas (también los diálogos) se identifican con el id de la app ante el escritorio.
    GLib.set_prgname(APP_ID)
    theme.register_fonts()
    return MisNotasApp().run(sys.argv)
