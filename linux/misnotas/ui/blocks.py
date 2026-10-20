"""Vistas de cada tipo de bloque del editor."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, Optional

from gi.repository import Gdk, Gio, GLib, Graphene, Gsk, Gtk, Pango

from ..core import inline_html
from ..core.models import CODE, HR, IMG, LINK, TODO, Block, Note, TodoItem
from ..state import FocusTarget
from .richtext import BlockText, LineField, open_url
from .widgets import hatched_area, icon_button, on_right_click, set_clipboard, window_of

if TYPE_CHECKING:
    from .editor import EditorContext


def link_host(url: str) -> str:
    s = url
    for prefix in ("https://", "http://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s.split("/")[0] if s else ""


class BlockRow(Gtk.Box):
    """Fila de un bloque: contenido + hueco a la derecha para la ✕ de eliminar (bloques especiales)."""
    kinds: tuple = ()

    def __init__(self, ctx: "EditorContext", note: Note, block: Block):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.ctx = ctx
        self.state = ctx.state
        self.note = note
        self.block = block
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.content.add_css_class("mn-block")
        self.append(self.content)
        self.remove_button: Optional[Gtk.Button] = None
        if not block.is_text:
            # Siempre presente (solo cambia la opacidad): así el ratón pasa del bloque a la ✕ sin perder el hover.
            self.remove_button = icon_button("window-close-symbolic", "Eliminar bloque",
                                             lambda: self.state.remove_block(self.block.id, self.note.id), "mn-icon", "tiny")
            self.remove_button.set_valign(Gtk.Align.START)
            self.remove_button.set_opacity(0)
            self.append(self.remove_button)
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda *_: self.remove_button.set_opacity(0 if self.note.is_trashed else 1))
            motion.connect("leave", lambda *_: self.remove_button.set_opacity(0))
            self.add_controller(motion)
        else:
            self.append(Gtk.Box(width_request=22))
        on_right_click(self, self._context_menu)

    def matches(self, block: Block) -> bool:
        return block.type in self.kinds

    def update(self, note: Note, block: Block):
        self.note = note
        self.block = block

    def focus(self, key: str, at_start: bool) -> bool:
        return False

    def focus_keys(self) -> list[str]:
        """Claves de foco que atiende este bloque."""
        return []

    def handles_focus(self, key: str) -> bool:
        return key in self.focus_keys()

    def flush(self):
        pass

    # Ayudas comunes de foco.

    def focused(self, key: str):
        self.state.active_block_id = self.block.id
        if self.state.focus and self.state.focus.same(FocusTarget(self.note.id, key)):
            self.state.focus = None

    def move(self, up: bool, item: Optional[int] = None):
        self.state.move_focus(self.block.id, up, self.note.id, item)

    def fresh(self) -> Block:
        n = self.state.note(self.note.id)
        return next((b for b in n.blocks if b.id == self.block.id), self.block) if n else self.block

    def update_block(self, change: Callable[[Block], None]):
        self.state.update_block(self.note.id, self.block.id, change)

    def _context_menu(self, x: float, y: float):
        if self.note.is_trashed:
            return
        menu = Gio.Menu()
        if self.block.is_text:
            menu.append("Convertir en párrafo" if self.block.type == "h" else "Convertir en encabezado",
                        f"win.block-heading::{self.block.id}")
        if len(self.note.blocks) > 1 or not self.block.is_text:
            menu.append("Eliminar bloque", f"win.block-remove::{self.block.id}")
        pop = Gtk.PopoverMenu.new_from_model(menu)
        pop.set_parent(self)
        pop.set_has_arrow(False)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
        pop.popup()


class ParagraphBlock(BlockRow):
    kinds = ("p", "h")

    def __init__(self, ctx, note, block):
        super().__init__(ctx, note, block)
        self.text = BlockText(rich=True, heading=block.type == "h")
        self.content.append(self.text)
        t = self.text
        t.on_focused = lambda: self.focused("block:" + self.block.id)
        t.on_change = lambda html: self.update_block(lambda b: setattr(b, "html", html))
        t.on_delete_empty = self._delete_empty
        t.on_divider = lambda before, after: self.state.insert_divider(self.block.id, before, after, self.note.id)
        t.on_move_up = lambda: self.move(True)
        t.on_move_down = lambda: self.move(False)
        self._apply(note, block)
        t.load(block.html or "")

    def _delete_empty(self):
        if len(self.note.blocks) > 1:
            self.state.remove_block(self.block.id, self.note.id)

    def _apply(self, note: Note, block: Block):
        heading = block.type == "h"
        if heading != self.text.heading:
            self.text.heading = heading
            (self.text.view.add_css_class if heading else self.text.view.remove_css_class)("heading")
            self.text.view.set_pixels_inside_wrap(0 if heading else 6)
            self.text.view.set_pixels_below_lines(0 if heading else 6)
        self.content.set_margin_top(10 if heading else 0)
        self.text.placeholder.set_label("Empieza a escribir…" if len(note.blocks) == 1 else "")

    def update(self, note, block):
        super().update(note, block)
        self._apply(note, block)
        self.text.set_value(block.html or "")

    def focus(self, key, at_start):
        if key != "block:" + self.block.id:
            return False
        self.text.grab(at_start)
        return True

    def focus_keys(self):
        return ["block:" + self.block.id]

    def flush(self):
        self.text.flush()


class TodoBlock(BlockRow):
    """Lista simple con viñetas. Se guarda como bloque `todo` (sin usar `done`) para no cambiar la API."""
    kinds = (TODO,)

    def __init__(self, ctx, note, block):
        self.fields: list[LineField] = []
        super().__init__(ctx, note, block)
        self.content.set_spacing(2)
        self._rebuild()

    def _rebuild(self):
        for f in self.fields:
            f.detach()
        while (child := self.content.get_first_child()) is not None:
            self.content.remove(child)
        self.fields = []
        for i, item in enumerate(self.block.items or []):
            row = Gtk.Box(spacing=10, height_request=30)
            dot = Gtk.Box(valign=Gtk.Align.CENTER, margin_start=4)
            dot.add_css_class("mn-bullet")
            row.append(dot)
            f = LineField("Elemento", "mn-line", "item")
            f.set_valign(Gtk.Align.CENTER)
            f.set_value(item.t)
            self._wire(f, i)
            row.append(f)
            self.content.append(row)
            self.fields.append(f)

    def _wire(self, f: LineField, i: int):
        key = f"todo:{self.block.id}:{i}"
        f.on_focused = lambda: self.focused(key)
        f.on_change = lambda v: self._update_items(lambda items: i < len(items) and setattr(items[i], "t", v))
        f.on_submit = lambda: self._submit(i)
        f.on_delete_empty = lambda: self._delete(i)
        f.on_move_up = lambda: self.move(True, i)
        f.on_move_down = lambda: self.move(False, i)

    def _update_items(self, change: Callable[[list[TodoItem]], None]):
        def apply(b: Block):
            items = b.items or []
            change(items)
            b.items = items
        self.update_block(apply)

    def _submit(self, i: int):
        items = self.fresh().items or []
        if i < len(items) and not items[i].t.strip():
            self.state.exit_list(self.block.id, i, self.note.id)
            return
        self._update_items(lambda items: items.insert(i + 1, TodoItem("")))
        self.state.set_focus(FocusTarget(self.note.id, f"todo:{self.block.id}:{i + 1}"))

    def _delete(self, i: int):
        items = self.fresh().items or []
        if len(items) > 1:
            self._update_items(lambda items: items.pop(i))
            self.state.set_focus(FocusTarget(self.note.id, f"todo:{self.block.id}:{max(0, i - 1)}"))
        else:
            self.state.remove_block(self.block.id, self.note.id)

    def update(self, note, block):
        super().update(note, block)
        items = block.items or []
        if len(items) != len(self.fields):
            self._rebuild()
            return
        for f, item in zip(self.fields, items):
            f.set_value(item.t)

    def focus(self, key, at_start):
        prefix = f"todo:{self.block.id}:"
        if not key.startswith(prefix):
            return False
        try:
            i = int(key[len(prefix):])
        except ValueError:
            return False
        if 0 <= i < len(self.fields):
            self.fields[i].grab(at_start)
            return True
        return False

    def focus_keys(self):
        return [f"todo:{self.block.id}:{i}" for i in range(len(self.fields))]

    def flush(self):
        for f in self.fields:
            f.flush()


class CodeBlock(BlockRow):
    kinds = (CODE,)

    def __init__(self, ctx, note, block):
        super().__init__(ctx, note, block)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class("mn-code")
        header = Gtk.Box()
        header.add_css_class("mn-code-header")
        self.lang = LineField("LENGUAJE", "mn-line", "lang")
        self.lang.set_hexpand(False)
        self.lang.set_size_request(140, -1)
        self.lang.set_value(block.lang or "")
        self.lang.on_change = lambda v: self.update_block(lambda b: setattr(b, "lang", v.upper()))
        header.append(self.lang)
        header.append(Gtk.Box(hexpand=True))
        self.copy_button = Gtk.Button(label="COPIAR")
        self.copy_button.add_css_class("mn-flat-text")
        self.copy_button.set_can_focus(False)
        self.copy_button.connect("clicked", lambda *_: self._copy())
        header.append(self.copy_button)
        box.append(header)

        self.text = BlockText(rich=False)
        self.text.set_margin_start(14)
        self.text.set_margin_end(14)
        self.text.set_margin_top(12)
        self.text.set_margin_bottom(12)
        t = self.text
        t.on_focused = lambda: self.focused("block:" + self.block.id)
        t.on_change = lambda v: self.update_block(lambda b: setattr(b, "text", v))
        t.on_move_up = lambda: self.move(True)
        t.on_move_down = lambda: self.move(False)
        t.load(block.text or "")
        box.append(self.text)
        self.content.append(box)

    def _copy(self):
        self.text.flush()
        set_clipboard(self.fresh().text or "")
        self.copy_button.set_label("COPIADO")
        GLib.timeout_add(1400, lambda: (self.copy_button.set_label("COPIAR"), False)[1])

    def update(self, note, block):
        super().update(note, block)
        self.lang.set_value(block.lang or "")
        self.text.set_value(block.text or "")

    def focus(self, key, at_start):
        if key != "block:" + self.block.id:
            return False
        self.text.grab(at_start)
        return True

    def focus_keys(self):
        return ["block:" + self.block.id]

    def flush(self):
        self.lang.flush()
        self.text.flush()


class LinkBlock(BlockRow):
    kinds = (LINK,)

    def __init__(self, ctx, note, block):
        super().__init__(ctx, note, block)
        card = Gtk.Box(spacing=14)
        card.add_css_class("mn-link")
        icon = Gtk.Image(icon_name="mn-link-symbolic", pixel_size=14)
        icon_box = Gtk.Box(valign=Gtk.Align.CENTER)
        icon_box.add_css_class("mn-link-icon")
        icon.set_hexpand(True)
        icon_box.append(icon)
        card.append(icon_box)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("mn-link-title")
        self.title.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        g = Gtk.GestureClick()
        g.connect("released", lambda *_: open_url(self, self.fresh().url or ""))
        self.title.add_controller(g)
        title_row = Gtk.Box()
        title_row.append(self.title)
        col.append(title_row)
        self.url = LineField("https://", "mn-line", "small")
        self.url.set_value(block.url or "")
        key = "url:" + block.id
        self.url.on_focused = lambda: self.focused(key)
        self.url.on_change = self._url_changed
        self.url.on_submit = self._submit
        self.url.on_move_up = lambda: self.move(True)
        self.url.on_move_down = lambda: self.move(False)
        col.append(self.url)
        card.append(col)
        self.content.append(card)
        self._apply(block)

    def _apply(self, block: Block):
        self.title.set_label(block.title if block.title else "Nuevo enlace")

    def _url_changed(self, v: str):
        def change(b: Block):
            # El título sigue al dominio mientras no se haya personalizado.
            auto = b.title is None or b.title == "Nuevo enlace" or b.title == link_host(b.url or "")
            b.url = v
            if auto:
                b.title = link_host(v) or "Nuevo enlace"
        self.update_block(change)

    def _submit(self):
        self.state.focus = None
        win = window_of(self)
        if win:
            win.set_focus(None)

    def update(self, note, block):
        super().update(note, block)
        self._apply(block)
        self.url.set_value(block.url or "")

    def focus(self, key, at_start):
        if key != "url:" + self.block.id:
            return False
        self.url.grab(at_start)
        return True

    def focus_keys(self):
        return ["url:" + self.block.id]

    def flush(self):
        self.url.flush()


class DividerBlock(BlockRow):
    """Línea horizontal. Se selecciona con un clic y se borra con Retroceso o Suprimir."""
    kinds = (HR,)

    def __init__(self, ctx, note, block):
        super().__init__(ctx, note, block)
        self.area = Gtk.Box(focusable=True, height_request=28)
        self.line = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER)
        self.line.add_css_class("mn-hr")
        self.area.append(self.line)
        self.content.append(self.area)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self.area.grab_focus())
        self.area.add_controller(click)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: (self.line.add_css_class("selected"), self.focused("hr:" + self.block.id)))
        focus.connect("leave", lambda *_: self.line.remove_css_class("selected"))
        self.area.add_controller(focus)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.area.add_controller(keys)

    def _key(self, ctrl, keyval, keycode, state):
        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            self.state.remove_block(self.block.id, self.note.id)
            return True
        if keyval == Gdk.KEY_Up:
            self.move(True)
            return True
        if keyval == Gdk.KEY_Down:
            self.move(False)
            return True
        if keyval == Gdk.KEY_Escape:
            win = window_of(self)
            if win:
                win.set_focus(None)
            return True
        return False

    def focus(self, key, at_start):
        if key != "hr:" + self.block.id:
            return False
        self.area.grab_focus()
        return True

    def focus_keys(self):
        return ["hr:" + self.block.id]


# MARK: - Imágenes

class TextureCache:
    _images: dict[str, Gdk.Texture] = {}
    _thumbs: dict[str, Gdk.Texture] = {}

    @classmethod
    def image(cls, path: str) -> Optional[Gdk.Texture]:
        if path not in cls._images:
            try:
                cls._images[path] = Gdk.Texture.new_from_filename(path)
            except GLib.Error:
                return None
        return cls._images[path]

    @classmethod
    def thumbnail(cls, path: str) -> Optional[Gdk.Texture]:
        if path not in cls._thumbs:
            try:
                from gi.repository import GdkPixbuf
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 120, 120, True)
                cls._thumbs[path] = Gdk.Texture.new_for_pixbuf(pb)
            except (GLib.Error, ImportError, ValueError):
                tex = cls.image(path)
                if tex is None:
                    return None
                cls._thumbs[path] = tex
        return cls._thumbs[path]


class ImageFrame(Gtk.Widget):
    """Imagen con asas en las esquinas para cambiar su tamaño manteniendo la proporción.
    Su alto depende del ancho disponible (altura-para-anchura)."""
    HANDLE = 11

    def __init__(self, texture: Gdk.Texture, width: Optional[float], on_resized: Callable[[float], None]):
        super().__init__()
        self.aspect = texture.get_height() / texture.get_width() if texture.get_width() > 0 else 1
        self.block_width = width
        self.live_width: Optional[float] = None
        self.on_resized = on_resized
        self._available = 0
        self._drag: Optional[tuple[bool, float]] = None  # (asa derecha, ancho inicial)
        self._hover = False

        self.picture = Gtk.Picture.new_for_paintable(texture)
        self.picture.set_content_fit(Gtk.ContentFit.FILL)
        self.picture.set_can_shrink(True)
        self.picture.add_css_class("mn-image")
        self.picture.set_overflow(Gtk.Overflow.HIDDEN)
        self.picture.set_parent(self)
        self.handles = []
        for i in range(4):
            h = Gtk.Box(visible=False, can_target=False)
            h.add_css_class("mn-handle")
            h.set_parent(self)
            self.handles.append(h)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_hover(True))
        motion.connect("leave", lambda *_: self._set_hover(False))
        motion.connect("motion", self._motion)
        self.add_controller(motion)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)

    def do_dispose(self):
        for child in [self.picture, *self.handles]:
            child.unparent()
        self.handles = []

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def _width_for(self, available: float) -> float:
        fitted = min(available, 420 / max(self.aspect, 0.01)) if available > 0 else 0
        w = self.live_width if self.live_width is not None else (self.block_width if self.block_width else fitted)
        return max(40.0, min(w, max(available, 40.0)))

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 40, 40, -1, -1
        # Sin ancho dado, el mínimo corresponde al ancho mínimo (40): el mínimo nunca supera al natural.
        available = for_size if for_size > 0 else 40
        h = math.ceil(self._width_for(available) * self.aspect)
        return h, h, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self._available = width
        w = self._width_for(width)
        h = w * self.aspect
        self.picture.allocate(int(w), int(h), -1, None)
        s = self.HANDLE
        for i, handle in enumerate(self.handles):
            x = (w if i % 2 else 0) - s / 2
            y = (h if i >= 2 else 0) - s / 2
            t = Gsk.Transform().translate(Graphene.Point().init(x, y))
            handle.allocate(s, s, -1, t)

    def _set_hover(self, on: bool):
        self._hover = on
        self._refresh_chrome()

    def _refresh_chrome(self):
        show = self._hover or self._drag is not None
        (self.picture.add_css_class if show else self.picture.remove_css_class)("hover")
        for h in self.handles:
            h.set_visible(show)

    def _corner_at(self, x: float, y: float) -> Optional[bool]:
        """Devuelve si el punto está en un asa (True = derecha) o None."""
        w = self._width_for(self._available)
        h = w * self.aspect
        for right in (False, True):
            cx = w if right else 0
            for cy in (0, h):
                if abs(x - cx) <= 9 and abs(y - cy) <= 9:
                    return right
        return None

    def _motion(self, ctrl, x, y):
        corner = self._corner_at(x, y)
        if corner is None:
            self.set_cursor(None)
        else:
            w = self._width_for(self._available)
            top = y < w * self.aspect / 2
            name = "nwse-resize" if corner != top else "nesw-resize"
            self.set_cursor(Gdk.Cursor.new_from_name(name))

    def _drag_begin(self, gesture, x, y):
        corner = self._corner_at(x, y)
        if corner is None:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self._drag = (corner, self._width_for(self._available))
        self._refresh_chrome()

    def _drag_update(self, gesture, dx, dy):
        if self._drag is None:
            return
        right, start = self._drag
        delta = dx if right else -dx
        self.live_width = max(40.0, min(self._available, start + delta))
        self.queue_resize()

    def _drag_end(self, gesture, dx, dy):
        if self._drag is None:
            return
        self._drag = None
        if self.live_width is not None:
            w = round(self.live_width)
            self.block_width = w
            self.live_width = None
            self.on_resized(w)
        self._refresh_chrome()


class ImageBlock(BlockRow):
    kinds = (IMG,)

    def __init__(self, ctx, note, block):
        super().__init__(ctx, note, block)
        self.content.set_spacing(8)
        self.content.set_margin_top(4)
        self.content.set_margin_bottom(4)
        self.holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.append(self.holder)
        self.caption = LineField("Pie de foto", "mn-line", "small")
        self.caption.set_value(block.caption or "")
        key = "caption:" + (block.attachment_id or "")
        self.caption.on_focused = lambda: self.focused(key)
        self.caption.on_change = lambda v: self.update_block(lambda b: setattr(b, "caption", v))
        self.caption.on_move_up = lambda: self.move(True)
        self.caption.on_move_down = lambda: self.move(False)
        self.content.append(self.caption)
        self._shown: Optional[str] = None
        self.frame: Optional[ImageFrame] = None
        self._load()

    def _load(self):
        id = self.block.attachment_id or ""
        path = self.state.local_image_path(id) if id else None
        marker = path or ""
        if marker == self._shown and (path or self.holder.get_first_child() is not None):
            if self.frame and self.frame.live_width is None and self.frame.block_width != self.block.width:
                self.frame.block_width = self.block.width
                self.frame.queue_resize()
            return
        self._shown = marker
        while (child := self.holder.get_first_child()) is not None:
            self.holder.remove(child)
        self.frame = None
        texture = TextureCache.image(path) if path else None
        if texture is not None:
            self.frame = ImageFrame(texture, self.block.width,
                                    lambda w: self.update_block(lambda b: setattr(b, "width", float(w))))
            self.holder.append(self.frame)
        else:
            over = Gtk.Overlay()
            area = hatched_area(10, 220)
            area.set_hexpand(True)
            frame = Gtk.Frame(child=area)
            frame.add_css_class("mn-image")
            frame.set_overflow(Gtk.Overflow.HIDDEN)
            over.set_child(frame)
            label = Gtk.Label(label="imagen", halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            label.add_css_class("mn-image-missing-label")
            over.add_overlay(label)
            self.holder.append(over)
            if id:
                self.ctx.sync.fetch_attachment(id)

    def update(self, note, block):
        super().update(note, block)
        self.caption.set_value(block.caption or "")
        self._load()

    def refresh_attachments(self):
        self._load()

    def focus(self, key, at_start):
        if key != "caption:" + (self.block.attachment_id or ""):
            return False
        self.caption.grab(at_start)
        return True

    def focus_keys(self):
        return ["caption:" + (self.block.attachment_id or "")]

    def flush(self):
        self.caption.flush()


BLOCK_TYPES = [ParagraphBlock, TodoBlock, CodeBlock, LinkBlock, ImageBlock, DividerBlock]


def make_block(ctx: "EditorContext", note: Note, block: Block) -> BlockRow:
    for cls in BLOCK_TYPES:
        if block.type in cls.kinds:
            return cls(ctx, note, block)
    # Tipo desconocido (de una versión más nueva): se muestra como párrafo con su texto.
    fallback = Block.paragraph(inline_html.escape(block.plain_text))
    fallback.id = block.id
    return ParagraphBlock(ctx, note, fallback)
