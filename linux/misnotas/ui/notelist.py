"""Columna central: búsqueda, cabecera de la vista y lista de notas."""
from __future__ import annotations

import weakref
from typing import Optional

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from ..core.models import Note
from ..core.text import find_folded
from ..state import ALL, FAVORITES, RECENTS, TRASH, AppState, notebook_nav
from .blocks import TextureCache
from .sidebar import popup_menu
from .widgets import NavRow, hatched_area, highlight_markup, hspacer, icon_button, relative_date


class NoteItem(GObject.Object):
    def __init__(self, id: str):
        super().__init__()
        self.id = id


class NoteRow(Gtk.Box):
    def __init__(self, view: "NoteListView"):
        super().__init__()
        self.view = view
        self.note_id: Optional[str] = None
        self.add_css_class("mn-note-row")
        inner = Gtk.Box(spacing=12, hexpand=True)
        inner.add_css_class("inner")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, single_line_mode=True)
        self.title.add_css_class("mn-note-title")
        self.snippet = Gtk.Label(xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, lines=2,
                                 ellipsize=Pango.EllipsizeMode.END, max_width_chars=10)
        self.snippet.add_css_class("mn-note-snippet")
        meta = Gtk.Box(spacing=8)
        self.date = Gtk.Label(xalign=0)
        self.meta = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        for l in (self.date, self.meta):
            l.add_css_class("mn-note-meta")
            meta.append(l)
        col.append(self.title)
        col.append(self.snippet)
        col.append(meta)
        inner.append(col)
        self.thumb_slot = Gtk.Box(valign=Gtk.Align.START)
        inner.append(self.thumb_slot)
        self.append(inner)
        self._thumb_key: Optional[str] = None

        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._pressed)
        self.add_controller(click)
        right = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        right.connect("pressed", self._menu)
        self.add_controller(right)
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", self._drag_prepare)
        self.add_controller(drag)

    def _pressed(self, gesture, n, x, y):
        if not self.note_id:
            return
        state = self.view.state
        mods = gesture.get_current_event_state()
        self.view.list.grab_focus()
        if mods & Gdk.ModifierType.CONTROL_MASK:
            state.toggle_mark(self.note_id)
        elif mods & Gdk.ModifierType.SHIFT_MASK:
            state.extend_mark(self.note_id)
        else:
            state.select_note(self.note_id)

    def _drag_prepare(self, source, x, y):
        if not self.note_id:
            return None
        return Gdk.ContentProvider.new_for_value(self.view.state.drag_payload(self.note_id))

    def _menu(self, gesture, n, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        note = self.view.state.note(self.note_id)
        if note is None:
            return
        menu = Gio.Menu()
        if note.is_trashed:
            menu.append("Restaurar", f"win.note-restore::{note.id}")
            menu.append("Eliminar definitivamente", f"win.note-delete::{note.id}")
        else:
            move = Gio.Menu()
            for nb in self.view.state.notebooks:
                item = Gio.MenuItem.new(nb.name, None)
                if nb.id != note.notebook_id:
                    item.set_action_and_target_value("win.note-move", GLib.Variant.new_string(f"{note.id}|{nb.id}"))
                else:
                    # Acción inexistente: el elemento aparece desactivado (es la libreta actual).
                    item.set_action_and_target_value("win.disabled", None)
                move.append_item(item)
            menu.append_submenu("Mover a", move)
            menu.append("Quitar de favoritas" if note.favorite else "Añadir a favoritas", f"win.note-favorite::{note.id}")
            menu.append("Mover a la Papelera", f"win.note-trash::{note.id}")
        popup_menu(self, menu, x, y)

    def bind(self, note_id: str):
        self.note_id = note_id
        self.refresh()

    def refresh(self):
        state = self.view.state
        note = state.note(self.note_id)
        if note is None:
            return
        q = state.trimmed_query
        active = (note.id == state.selected_id) if not state.multi_selection else state.is_marked(note.id)
        (self.add_css_class if active else self.remove_css_class)("active")
        self.title.set_markup(highlight_markup(note.title or "Sin título", q))
        self.snippet.set_markup(highlight_markup(snippet(note.body_text, q), q))
        self.date.set_label(relative_date(note.updated_at))
        meta = ""
        if not (state.nav[0] == "notebook" and not state.is_searching):
            meta = state.notebook_name(note.notebook_id)
        self.meta.set_label(meta)
        self._set_thumbnail(note)

    def _set_thumbnail(self, note: Note):
        state = self.view.state
        att = next((b.attachment_id for b in note.blocks if b.type == "img"), None)
        path = state.local_image_path(att) if att else None
        key = f"{path}|{att}|{state.attachments_version}" if att else None
        if key == self._thumb_key:
            return
        self._thumb_key = key
        while (child := self.thumb_slot.get_first_child()) is not None:
            self.thumb_slot.remove(child)
        if not att:
            return
        tex = TextureCache.thumbnail(path) if path else None
        if tex is not None:
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(46, 46)
            pic.set_can_shrink(True)
            pic.add_css_class("mn-thumb")
            pic.set_overflow(Gtk.Overflow.HIDDEN)
            self.thumb_slot.append(pic)
        else:
            area = hatched_area(6)
            area.set_size_request(46, 46)
            frame = Gtk.Frame(child=area)
            frame.add_css_class("mn-thumb")
            frame.set_overflow(Gtk.Overflow.HIDDEN)
            self.thumb_slot.append(frame)


def snippet(text: str, q: str) -> str:
    if not text:
        return "Sin contenido"
    if q:
        r = find_folded(text, q)
        if r and r[0] > 50:
            return "…" + text[r[0] - 40:][:160]
    return text[:160]


class NoteListView(Gtk.Box):
    def __init__(self, state: AppState):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, width_request=330)
        self.state = state
        self.add_css_class("mn-notelist")

        # Barra superior: búsqueda y nueva nota.
        top = Gtk.Box(spacing=8)
        top.add_css_class("mn-topbar")
        self.show_sidebar = icon_button("sidebar-show-symbolic", "Mostrar barra lateral  F9",
                                        lambda: state.set_sidebar_open(True), "muted")
        self.show_sidebar.set_valign(Gtk.Align.CENTER)
        top.append(self.show_sidebar)
        search = Gtk.Box(spacing=7, hexpand=True, valign=Gtk.Align.CENTER)
        search.add_css_class("mn-search")
        search.append(Gtk.Image(icon_name="system-search-symbolic", pixel_size=12))
        self.search = Gtk.Text(placeholder_text="Buscar  Ctrl+F", hexpand=True)
        self.search.connect("changed", lambda e: setattr(state, "query", e.get_text()))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._search_key)
        self.search.add_controller(keys)
        search.append(self.search)
        self.clear = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER, visible=False)
        self.clear.add_css_class("clear")
        self.clear.set_can_focus(False)
        self.clear.connect("clicked", lambda *_: self.search.set_text(""))
        search.append(self.clear)
        top.append(search)
        new = icon_button("document-edit-symbolic", "Nueva nota  Ctrl+N", state.new_note)
        new.set_size_request(32, -1)
        new.set_valign(Gtk.Align.CENTER)
        top.append(new)
        self.append(Gtk.WindowHandle(child=top))

        # Cabecera.
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        header.add_css_class("mn-list-header")
        line = Gtk.Box(spacing=12)
        title_box = Gtk.Box(spacing=6)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("mn-list-title")
        title_box.append(self.title)
        self.chevron = Gtk.Image(icon_name="pan-down-symbolic", pixel_size=11)
        self.chevron.add_css_class("mn-note-meta")
        title_box.append(self.chevron)
        g = Gtk.GestureClick()
        g.connect("released", lambda *_: self._open_nav_menu())
        title_box.add_controller(g)
        self.title_box = title_box
        line.append(title_box)
        line.append(hspacer())
        self.count = Gtk.Label(valign=Gtk.Align.CENTER)
        self.count.add_css_class("mn-list-count")
        line.append(self.count)
        header.append(line)
        self.scope = Gtk.Box(homogeneous=True)
        self.scope.add_css_class("mn-scope")
        self.scope_all = Gtk.Button(label="Todas las notas", can_focus=False)
        self.scope_all.connect("clicked", lambda *_: state.set_scope("all"))
        self.scope_current = Gtk.Button(can_focus=False)
        self.scope_current.connect("clicked", lambda *_: state.set_scope("current"))
        self.scope.append(self.scope_all)
        self.scope.append(self.scope_current)
        header.append(self.scope)
        self.append(header)
        self.nav_popover = Gtk.Popover(has_arrow=False)
        self.nav_popover.add_css_class("mn-popover")
        self.nav_popover.set_parent(title_box)

        # Lista.
        self.store = Gio.ListStore.new(NoteItem)
        self.ids: list[str] = []
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda f, item: item.set_child(NoteRow(self)))
        factory.connect("bind", self._bind)
        factory.connect("unbind", self._unbind)
        self.bound: "weakref.WeakSet[NoteRow]" = weakref.WeakSet()
        self.list = Gtk.ListView(model=Gtk.NoSelection(model=self.store), factory=factory, focusable=True)
        self.list.add_css_class("mn-notes")
        list_keys = Gtk.EventControllerKey()
        list_keys.connect("key-pressed", self._list_key)
        self.list.add_controller(list_keys)
        self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list)
        self.empty = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, valign=Gtk.Align.START, vexpand=True,
                               margin_top=48, margin_start=16, margin_end=16)
        self.empty.add_css_class("mn-empty")
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(self.scroller, "list")
        self.stack.add_named(self.empty, "empty")
        self.append(self.stack)

        state.subscribe(self._changed)
        self._changed({"list", "nav", "query", "sidebar"})

    # MARK: Lista

    def _bind(self, factory, item):
        row: NoteRow = item.get_child()
        row.bind(item.get_item().id)
        self.bound.add(row)

    def _unbind(self, factory, item):
        row = item.get_child()
        row.note_id = None
        self.bound.discard(row)

    def _sync_store(self, ids: list[str]):
        """Actualiza el modelo tocando solo el tramo que cambió (una nota editada sube arriba)."""
        old = self.ids
        if ids == old:
            return False
        prefix = 0
        while prefix < min(len(old), len(ids)) and old[prefix] == ids[prefix]:
            prefix += 1
        suffix = 0
        while (suffix < min(len(old), len(ids)) - prefix
               and old[len(old) - 1 - suffix] == ids[len(ids) - 1 - suffix]):
            suffix += 1
        removed = len(old) - prefix - suffix
        added = [NoteItem(i) for i in ids[prefix:len(ids) - suffix]]
        self.store.splice(prefix, removed, added)
        self.ids = list(ids)
        return True

    def _changed(self, topics: set):
        s = self.state
        if topics & {"list", "notes", "nav", "query", "marks", "selection", "attachments", "notebooks"}:
            lst = s.list
            self._sync_store([n.id for n in lst])
            for row in list(self.bound):
                if row.note_id:
                    row.refresh()
            self.stack.set_visible_child_name("list" if lst else "empty")
            self.empty.set_label(self._empty_text())
            self.count.set_label("1 nota" if len(lst) == 1 else f"{len(lst)} notas")
        if topics & {"nav", "query", "sidebar", "notebooks"}:
            self.title.set_label((("Resultados" if s.is_searching else s.nav_label(s.nav)) or "").upper())
            collapsible = not s.sidebar_open and not s.is_searching
            self.chevron.set_visible(collapsible)
            self.title_box.set_tooltip_text("Cambiar de libreta" if collapsible else None)
            self.title_box.set_cursor(Gdk.Cursor.new_from_name("pointer") if collapsible else None)
            self.show_sidebar.set_visible(not s.sidebar_open)
            self.scope.set_visible(s.is_searching)
            self.scope_current.set_label("Vista actual" if s.nav == ALL else s.nav_label(s.nav))
            for b, on in ((self.scope_all, s.scope == "all"), (self.scope_current, s.scope == "current")):
                (b.add_css_class if on else b.remove_css_class)("on")
            self.clear.set_visible(s.is_searching)
            if self.search.get_text() != s.query:
                self.search.set_text(s.query)
        if "selection" in topics and s.selected_id in self.ids:
            self.list.scroll_to(self.ids.index(s.selected_id), Gtk.ListScrollFlags.NONE, None)

    def _empty_text(self) -> str:
        s = self.state
        if s.is_searching:
            return f"Nada coincide con «{s.trimmed_query}»."
        if s.nav == TRASH:
            return "La Papelera está vacía."
        if s.nav == RECENTS:
            return "Aún no has visto ninguna nota."
        return "No hay notas aquí. Pulsa Ctrl+N para crear una."

    # MARK: Teclado

    def focus_search(self):
        self.search.grab_focus()

    def _search_key(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.search.set_text("")
            self.list.grab_focus()
            return True
        if keyval == Gdk.KEY_Down:
            self.list.grab_focus()
            return True
        return False

    def _list_key(self, ctrl, keyval, keycode, state):
        s = self.state
        if state & Gdk.ModifierType.CONTROL_MASK and keyval in (Gdk.KEY_a, Gdk.KEY_A):
            s.mark_all()
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down) and self.ids:
            i = self.ids.index(s.selected_id) if s.selected_id in self.ids else -1
            j = max(0, i - 1) if keyval == Gdk.KEY_Up else min(len(self.ids) - 1, i + 1)
            if state & Gdk.ModifierType.SHIFT_MASK:
                s.extend_mark(self.ids[j])
            else:
                s.select_note(self.ids[j])
            return True
        return False

    # MARK: Menú de vistas (con la barra lateral oculta)

    def _open_nav_menu(self):
        s = self.state
        if s.sidebar_open or s.is_searching:
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, width_request=240)

        def item(title, count, nav):
            row = NavRow("mn-notebook-symbolic", title, count, s.nav == nav,
                         lambda: (self.nav_popover.popdown(), s.select_nav(nav)))
            box.append(row)

        item("Todas las notas", len(s.live_notes), ALL)
        item("Recientes", len(s.recent_notes), RECENTS)
        item("Favoritas", s.favorite_count, FAVORITES)
        for nb in s.notebooks:
            item(nb.name, s.count_in(nb), notebook_nav(nb.id))
        sep = Gtk.Box()
        sep.add_css_class("mn-menu-sep")
        box.append(sep)
        show = Gtk.Box()
        show.add_css_class("mn-menu-item")
        show.append(Gtk.Label(label="Mostrar barra lateral", xalign=0, hexpand=True))
        g = Gtk.GestureClick()
        g.connect("released", lambda *_: (self.nav_popover.popdown(), s.set_sidebar_open(True)))
        show.add_controller(g)
        box.append(show)
        self.nav_popover.set_child(box)
        self.nav_popover.popup()
