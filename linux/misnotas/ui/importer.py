"""Importación de archivos .enex, con las etapas del diseño: elegir → revisar → importar → listo."""
from __future__ import annotations

import os
import threading
from typing import Optional

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from ..core.enex import EnexNote, parse_file
from ..core.models import Block, Note, now_ms
from ..state import ALL, AppState, notebook_nav
from .widgets import gradient_check, hspacer, set_check, text_button


class ImportWindow(Gtk.Window):
    def __init__(self, parent: Optional[Gtk.Window], state: AppState):
        super().__init__(modal=True, transient_for=parent, resizable=False, default_width=480,
                         title="Importar de Evernote")
        self.state = state
        self.add_css_class("mn-dialog")
        self.set_titlebar(Gtk.Box(visible=False))
        self.files: list[tuple[str, list[EnexNote]]] = []
        self.failures: list[str] = []
        self.per_file = False
        self.stage = "pick"
        self.target_nav = ALL
        self._cancelled = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24,
                      margin_start=24, margin_end=24)
        self.set_child(box)
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label(label="IMPORTAR DE EVERNOTE", xalign=0)
        title.add_css_class("mn-dialog-title")
        head.append(title)
        sub = Gtk.Label(label="En Evernote, selecciona una libreta y usa Archivo › Exportar como .enex.", xalign=0,
                        wrap=True)
        sub.add_css_class("mn-dialog-subtitle")
        head.append(sub)
        box.append(head)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.body)
        self.buttons = Gtk.Box(spacing=8)
        box.append(self.buttons)

        esc = Gtk.ShortcutController()
        esc.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("Escape"),
                                          Gtk.CallbackAction.new(lambda *_: (self._close(), True)[1])))
        self.add_controller(esc)
        self.connect("close-request", lambda *_: self.stage == "running")
        self._render()

    def _close(self):
        if self.stage != "running":
            self.destroy()

    def _render(self):
        while (child := self.body.get_first_child()) is not None:
            self.body.remove(child)
        while (child := self.buttons.get_first_child()) is not None:
            self.buttons.remove(child)
        if self.stage in ("pick", "parsing"):
            self.body.append(self._drop_zone())
        elif self.stage == "ready":
            self.body.append(self._review())
        elif self.stage == "running":
            self.body.append(self._running())
        else:
            self.body.append(self._done())

        self.buttons.append(hspacer())
        if self.stage != "done":
            self.buttons.append(text_button("Cancelar", self._cancel, "mn-secondary"))
        if self.stage == "ready":
            ok = text_button("Importar", self._run_import, "mn-primary")
            ok.set_sensitive(bool(self.files))
            self.buttons.append(ok)
            self.set_default_widget(ok)
        elif self.stage == "done":
            ok = text_button("Ver notas", self._show_notes, "mn-primary")
            self.buttons.append(ok)
            self.set_default_widget(ok)

    def _cancel(self):
        self._cancelled = True
        self.stage = "pick"
        self.destroy()

    # MARK: Elegir

    def _drop_zone(self) -> Gtk.Widget:
        zone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER)
        zone.add_css_class("mn-dropzone")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, vexpand=True)
        if self.stage == "parsing":
            spinner = Gtk.Spinner(spinning=True)
            inner.append(spinner)
            inner.append(Gtk.Label(label="Leyendo archivos…"))
        else:
            inner.append(Gtk.Image(icon_name="document-save-symbolic", pixel_size=26))
            inner.append(Gtk.Label(label="Arrastra archivos .enex aquí o haz clic para elegirlos"))
        zone.append(inner)
        zone.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: zone.add_css_class("hover"))
        motion.connect("leave", lambda *_: zone.remove_css_class("hover"))
        zone.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._pick())
        zone.add_controller(click)
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", lambda *_: (zone.add_css_class("hover"), Gdk.DragAction.COPY)[1])
        drop.connect("leave", lambda *_: zone.remove_css_class("hover"))
        drop.connect("drop", self._dropped)
        zone.add_controller(drop)
        return zone

    def _dropped(self, target, value, x, y):
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        self._load([p for p in paths if p.lower().endswith(".enex")])
        return True

    def _pick(self):
        if self.stage != "pick":
            return
        dialog = Gtk.FileDialog(title="Elegir archivos .enex", modal=True)
        f = Gtk.FileFilter(name="Exportación de Evernote (.enex)")
        f.add_pattern("*.enex")
        f.add_pattern("*.ENEX")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.set_default_filter(f)

        def done(dlg, result):
            try:
                files = dlg.open_multiple_finish(result)
            except GLib.Error:
                return
            self._load([files.get_item(i).get_path() for i in range(files.get_n_items()) if files.get_item(i).get_path()])
        dialog.open_multiple(self, None, done)

    def _load(self, paths: list[str]):
        if not paths:
            return
        self.stage = "parsing"
        self._render()

        def work():
            results = []
            for p in paths:
                try:
                    results.append((p, parse_file(p)))
                except Exception:  # noqa: BLE001 — archivo dañado o no es .enex
                    results.append((p, None))

            def done():
                self.files = [(p, notes) for p, notes in results if notes is not None]
                self.failures = [os.path.basename(p) for p, notes in results if notes is None]
                self.stage = "ready" if self.files or self.failures else "pick"
                self._render()
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    # MARK: Revisar

    def _review(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        listing.add_css_class("mn-filelist")
        for path, notes in self.files:
            row = Gtk.Box()
            name = Gtk.Label(label=os.path.basename(path), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            name.add_css_class("mn-filename")
            row.append(name)
            count = Gtk.Label(label="1 nota" if len(notes) == 1 else f"{len(notes)} notas")
            count.add_css_class("mn-list-count")
            row.append(count)
            listing.append(row)
        for name in self.failures:
            row = Gtk.Box()
            l = Gtk.Label(label=f"{name}: no se pudo leer", xalign=0)
            l.add_css_class("mn-orange")
            row.append(l)
            listing.append(row)
        box.append(listing)
        option = Gtk.Box(spacing=10)
        check = gradient_check(self.per_file)
        option.append(check)
        option.append(Gtk.Label(label="Crear una libreta por archivo", xalign=0))

        def toggle(*_):
            self.per_file = not self.per_file
            set_check(check, self.per_file)
        g = Gtk.GestureClick()
        g.connect("released", toggle)
        option.add_controller(g)
        box.append(option)
        return box

    # MARK: Importar

    def _running(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        line = Gtk.Box()
        line.append(Gtk.Label(label="Importando notas…", xalign=0, hexpand=True))
        self.percent = Gtk.Label(label="0%")
        self.percent.add_css_class("mn-list-count")
        line.append(self.percent)
        box.append(line)
        self.progress = Gtk.ProgressBar()
        self.progress.add_css_class("mn-progress")
        box.append(self.progress)
        return box

    def _run_import(self):
        self.stage = "running"
        self._render()
        total = max(1, sum(len(notes) for _, notes in self.files))
        jobs: list[tuple[str, list[EnexNote]]] = []
        notebook_ids: list[str] = []
        for path, notes in self.files:
            name = os.path.splitext(os.path.basename(path))[0] if self.per_file else "Importado de Evernote"
            nb = self.state.create_notebook(name)
            if nb is None:
                continue
            if nb.id not in notebook_ids:
                notebook_ids.append(nb.id)
            # Lotes pequeños para que la barra de progreso avance.
            for i in range(0, len(notes), 40):
                jobs.append((nb.id, notes[i:i + 40]))
        imported = [0]

        def step():
            if self._cancelled:
                return False
            if not jobs:
                self._finish(imported[0], notebook_ids)
                return False
            nb_id, chunk = jobs.pop(0)
            batch = []
            for e in chunk:
                created = e.created or now_ms()
                blocks = list(e.blocks)
                if not blocks or blocks[-1].type != "p":
                    blocks.append(Block.paragraph())
                batch.append(Note(notebook_id=nb_id, title=e.title, blocks=blocks, created_at=created,
                                  updated_at=e.updated or created))
            try:
                self.state.repo.insert(batch)
            except Exception as err:  # noqa: BLE001
                self.state.on_error(str(err))
                self.stage = "pick"
                self.destroy()
                return False
            imported[0] += len(batch)
            fraction = imported[0] / total
            self.progress.set_fraction(fraction)
            self.percent.set_label(f"{int(fraction * 100)}%")
            return True
        GLib.idle_add(step)

    def _finish(self, imported: int, notebook_ids: list[str]):
        self.state.reload()
        self.state.on_local_change()
        self.target_nav = notebook_nav(notebook_ids[0]) if len(notebook_ids) == 1 else ALL
        nb_text = "1 libreta" if len(notebook_ids) == 1 else f"{len(notebook_ids)} libretas"
        self.summary = ("1 nota importada" if imported == 1 else f"{imported} notas importadas") + " en " + nb_text + "."
        self.stage = "done"
        self._render()

    def _done(self) -> Gtk.Widget:
        box = Gtk.Box(spacing=10)
        icon = Gtk.Image(icon_name="object-select-symbolic", pixel_size=14)
        icon.add_css_class("mn-orange")
        box.append(icon)
        box.append(Gtk.Label(label=self.summary, xalign=0, wrap=True))
        return box

    def _show_notes(self):
        self.state.select_nav(self.target_nav)
        self.destroy()
