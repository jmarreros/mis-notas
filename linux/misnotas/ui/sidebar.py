"""Barra lateral: vistas, libretas, Papelera y estado de la sincronización."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from ..state import ALL, FAVORITES, RECENTS, TRASH, AppState, notebook_nav
from ..sync import relative_sync_text
from .widgets import NavRow, confirm, hspacer, icon_button, on_right_click, prompt

if TYPE_CHECKING:
    from ..sync import SyncCoordinator

# Distingue una libreta arrastrada de una nota (ambas viajan como texto).
NOTEBOOK_PREFIX = "libreta:"


def popup_menu(widget: Gtk.Widget, menu: Gio.Menu, x: float, y: float):
    pop = Gtk.PopoverMenu.new_from_model(menu)
    pop.set_parent(widget)
    pop.set_has_arrow(False)
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    pop.set_pointing_to(rect)
    pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
    pop.popup()


def handle_drop(state: AppState, payload: str, notebook_id: str) -> bool:
    ids = [s for s in payload.split("\n") if s]
    notes = [i for i in ids if not i.startswith(NOTEBOOK_PREFIX)]
    if len(notes) > 1:
        state.move_many(notes, notebook_id)
        return True
    for id in ids:
        if id.startswith(NOTEBOOK_PREFIX):
            state.move_notebook(id[len(NOTEBOOK_PREFIX):], notebook_id)
        else:
            state.move(id, notebook_id)
    return bool(ids)


class SyncStatusRow(Gtk.Box):
    def __init__(self, sync: "SyncCoordinator", open_settings: Callable[[], None]):
        super().__init__(spacing=7, hexpand=True)
        self.sync = sync
        self.open_settings = open_settings
        self.add_css_class("mn-sync-row")
        self.icon = Gtk.Image(pixel_size=11)
        self.label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, hexpand=True)
        self.append(self.icon)
        self.append(self.label)
        g = Gtk.GestureClick()
        g.connect("released", lambda *_: self._clicked())
        self.add_controller(g)
        sync.subscribe(self.refresh)
        self.refresh()

    def _clicked(self):
        if self.sync.status[0] == "not_configured":
            self.open_settings()
        else:
            self.sync.sync_now()

    def refresh(self):
        st = self.sync.status
        kind = st[0]
        for c in ("warn", "error"):
            self.remove_css_class(c)
        if kind == "not_configured":
            icon, text = "mn-cloud-off-symbolic", "Configurar servidor…"
            self.add_css_class("error")
            self.set_tooltip_text("Configurar el servidor")
        else:
            self.set_tooltip_text("Sincronizar ahora")
            if kind == "syncing":
                icon, text = "view-refresh-symbolic", "Sincronizando…"
            elif kind == "offline":
                icon, text = "network-offline-symbolic", "Sin conexión: cambios guardados en este equipo"
                self.add_css_class("warn")
            elif kind == "error":
                icon, text = "dialog-warning-symbolic", st[1]
                self.add_css_class("error")
                self.set_tooltip_text(st[1])
            else:
                icon = "mn-cloud-ok-symbolic"
                text = relative_sync_text(st[1]) if len(st) > 1 and st[1] else "Sincronizado"
        self.icon.set_from_icon_name(icon)
        self.label.set_label(text)


class Sidebar(Gtk.Box):
    def __init__(self, state: AppState, sync: "SyncCoordinator", open_settings: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, width_request=232)
        self.state = state
        self.add_css_class("mn-sidebar")

        top = Gtk.Box(height_request=52)
        top.set_margin_start(16)
        top.set_margin_end(12)
        top.append(hspacer())
        hide = icon_button("sidebar-show-symbolic", "Ocultar barra lateral  F9",
                           lambda: state.set_sidebar_open(False), "muted")
        hide.set_valign(Gtk.Align.CENTER)
        top.append(hide)
        self.append(Gtk.WindowHandle(child=top))

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_start(10)
        content.set_margin_end(10)
        content.set_margin_top(4)
        content.set_margin_bottom(12)
        views = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.row_all = NavRow("text-x-generic-symbolic", "Todas las notas", 0, False, lambda: state.select_nav(ALL), tall=True)
        self.row_recents = NavRow("document-open-recent-symbolic", "Recientes", 0, False,
                                  lambda: state.select_nav(RECENTS), tall=True)
        self.row_favorites = NavRow("non-starred-symbolic", "Favoritas", 0, False,
                                    lambda: state.select_nav(FAVORITES), tall=True)
        for r in (self.row_all, self.row_recents, self.row_favorites):
            views.append(r)
        content.append(views)

        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header = Gtk.Box(height_request=22, margin_bottom=2)
        header.set_margin_start(9)
        title = Gtk.Label(label="LIBRETAS", xalign=0)
        title.add_css_class("mn-section-title")
        header.append(title)
        header.append(hspacer())
        add = icon_button("list-add-symbolic", "Nueva libreta", self._new_notebook, "small")
        header.append(add)
        section.append(header)
        self.notebook_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        section.append(self.notebook_box)
        content.append(section)
        scroller.set_child(content)
        self.append(scroller)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        bottom.add_css_class("mn-sidebar-bottom")
        self.row_trash = NavRow("user-trash-symbolic", "Papelera", 0, False, lambda: state.select_nav(TRASH))
        on_right_click(self.row_trash, self._trash_menu)
        bottom.append(self.row_trash)
        status = Gtk.Box()
        status.append(SyncStatusRow(sync, open_settings))
        gear = icon_button("emblem-system-symbolic", "Servidor y sincronización  Ctrl+,", open_settings, "small")
        status.append(gear)
        bottom.append(status)
        self.append(bottom)

        self._notebook_rows: dict[str, NavRow] = {}
        self._notebook_order: list[tuple[str, str]] = []
        state.subscribe(self._changed)
        self.refresh()

    def _changed(self, topics: set):
        if topics & {"notebooks", "counts", "nav", "query", "notes", "list"}:
            self.refresh()

    def _active(self, nav: tuple) -> bool:
        return not self.state.is_searching and self.state.nav == nav

    def refresh(self):
        s = self.state
        live = s.live_notes
        self.row_all.set_values("Todas las notas", len(live), self._active(ALL))
        self.row_recents.set_values("Recientes", len(s.recent_notes), self._active(RECENTS))
        self.row_favorites.set_values("Favoritas", sum(1 for n in live if n.favorite), self._active(FAVORITES))
        self.row_trash.set_values("Papelera", s.trash_count, self._active(TRASH))

        counts: dict[str, int] = {}
        for n in live:
            if n.notebook_id:
                counts[n.notebook_id] = counts.get(n.notebook_id, 0) + 1
        order = [(nb.id, nb.name) for nb in s.notebooks]
        if order != self._notebook_order:
            # Cambió la lista de libretas: se reconstruye.
            while (child := self.notebook_box.get_first_child()) is not None:
                self.notebook_box.remove(child)
            self._notebook_rows = {}
            for nb in s.notebooks:
                row = NavRow("mn-notebook-symbolic", nb.name, 0, False,
                             lambda id=nb.id: s.select_nav(notebook_nav(id)))
                self._setup_notebook_row(row, nb.id)
                self.notebook_box.append(row)
                self._notebook_rows[nb.id] = row
            self._notebook_order = order
        for nb in s.notebooks:
            self._notebook_rows[nb.id].set_values(nb.name, counts.get(nb.id, 0), self._active(notebook_nav(nb.id)))

    def _setup_notebook_row(self, row: NavRow, id: str):
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", lambda *_: Gdk.ContentProvider.new_for_value(NOTEBOOK_PREFIX + id))
        row.add_controller(drag)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        drop.connect("enter", lambda *_: (row.add_css_class("drop-target"), Gdk.DragAction.MOVE)[1])
        drop.connect("leave", lambda *_: row.remove_css_class("drop-target"))
        drop.connect("drop", lambda t, value, x, y: (row.remove_css_class("drop-target"),
                                                     handle_drop(self.state, value, id))[1])
        row.add_controller(drop)
        on_right_click(row, lambda x, y: self._notebook_menu(row, id, x, y))

    def _notebook_menu(self, row: Gtk.Widget, id: str, x: float, y: float):
        menu = Gio.Menu()
        menu.append("Renombrar…", f"win.notebook-rename::{id}")
        menu.append("Eliminar…", f"win.notebook-delete::{id}")
        popup_menu(row, menu, x, y)

    def _trash_menu(self, x: float, y: float):
        menu = Gio.Menu()
        menu.append("Vaciar Papelera", "win.empty-trash")
        popup_menu(self.row_trash, menu, x, y)

    def _new_notebook(self):
        def done(name: str):
            nb = self.state.create_notebook(name)
            if nb:
                self.state.select_nav(notebook_nav(nb.id))
        prompt(self.get_root(), "Nueva libreta", "Crear", done)

    def rename_notebook(self, id: str):
        nb = next((n for n in self.state.notebooks if n.id == id), None)
        if nb:
            prompt(self.get_root(), "Renombrar libreta", "Renombrar", lambda name: self.state.rename_notebook(nb, name),
                   text=nb.name)

    def delete_notebook(self, id: str):
        nb = next((n for n in self.state.notebooks if n.id == id), None)
        if nb:
            confirm(self.get_root(), f"¿Eliminar la libreta «{nb.name}»?", "Sus notas se moverán a la Papelera.",
                    "Eliminar", lambda: self.state.delete_notebook(nb))
