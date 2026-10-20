"""Colores, tipografías e iconos del diseño (mismo tema oscuro que la app de macOS)."""
from __future__ import annotations

import ctypes
import os

from gi.repository import Gdk, Gtk

from ..platform import RESOURCES

ORANGE = "#FF5500"
YELLOW = "#FFB800"

CSS = """
@define-color mn_window #000000;
@define-color mn_sidebar #111111;
@define-color mn_border #222222;
@define-color mn_divider #1A1A1A;
@define-color mn_field #1A1A1A;
@define-color mn_field_border #2A2A2A;
@define-color mn_hover #1F1F1F;
@define-color mn_popover #161616;
@define-color mn_text #E6E6E6;
@define-color mn_muted #888888;
@define-color mn_soft #A0A0A0;
@define-color mn_icon #CCCCCC;
@define-color mn_orange #FF5500;
@define-color mn_yellow #FFB800;

window.mn-window, window.mn-dialog {
  background-color: @mn_window;
  color: @mn_text;
  font-family: "DM Sans";
  font-size: 14px;
}
window.mn-dialog { background-color: @mn_popover; }

/* Barra lateral */
.mn-sidebar { background-color: @mn_sidebar; border-right: 1px solid @mn_border; }
.mn-sidebar-bottom { border-top: 1px solid @mn_border; padding: 8px 10px; }
.mn-section-title { font-size: 11px; font-weight: 500; letter-spacing: 1.3px; color: @mn_muted; }
.mn-nav-row { border-radius: 5px; padding: 0 9px; min-height: 28px; color: @mn_text; }
.mn-nav-row.tall { min-height: 30px; font-weight: 500; }
.mn-nav-row:hover { background-color: #1C1C1C; }
.mn-nav-row.active { background-color: #2A2A2A; color: white; }
.mn-nav-row .count { font-size: 12px; color: @mn_muted; }
.mn-nav-row.active .count { color: @mn_soft; }
.mn-nav-row.drop-target { box-shadow: inset 0 0 0 1px @mn_orange; }
.mn-sync-row { font-size: 11.5px; color: #666666; padding: 0 9px; min-height: 24px; }
.mn-sync-row.warn { color: @mn_yellow; }
.mn-sync-row.error { color: @mn_orange; }

/* Botones de icono */
button.mn-icon {
  background: none; border: none; box-shadow: none; min-width: 28px; min-height: 28px;
  padding: 0; border-radius: 5px; color: @mn_icon; -gtk-icon-size: 14px;
}
button.mn-icon:hover { background-color: @mn_hover; color: white; }
button.mn-icon.muted { color: #999999; }
button.mn-icon.small { min-width: 22px; min-height: 22px; -gtk-icon-size: 11px; color: @mn_muted; }
button.mn-icon.tiny { min-width: 22px; min-height: 22px; -gtk-icon-size: 9px; color: @mn_muted; }
button.mn-icon.favorite { color: #F5C542; }
button.mn-icon:disabled { opacity: 0.35; }
.mn-toolbar-sep { background-color: @mn_field_border; min-width: 1px; min-height: 18px; margin: 0 6px; }

/* Botones de texto */
button.mn-primary {
  background: white; color: black; border: none; box-shadow: none; border-radius: 4px;
  font-size: 13px; font-weight: 600; min-height: 32px; padding: 0 16px;
}
button.mn-primary:hover { background: #E8E8E8; }
button.mn-primary:disabled { opacity: 0.4; }
button.mn-primary.compact { font-size: 12px; min-height: 26px; padding: 0 12px; }
button.mn-secondary {
  background: none; color: white; border: 1px solid #333333; box-shadow: none; border-radius: 4px;
  font-size: 13px; min-height: 32px; padding: 0 16px;
}
button.mn-secondary:hover { background-color: @mn_hover; }
button.mn-secondary:disabled { opacity: 0.4; }
button.mn-secondary.compact { font-size: 12px; min-height: 26px; padding: 0 12px; }
button.mn-secondary.destructive { color: @mn_orange; }
button.mn-flat-text {
  background: none; border: none; box-shadow: none; padding: 0 4px; min-height: 0;
  font-size: 11px; letter-spacing: 1.3px; color: #AAAAAA;
}
button.mn-flat-text:hover { color: white; }

/* Lista de notas */
.mn-notelist { border-right: 1px solid @mn_border; }
.mn-topbar { min-height: 52px; padding: 0 12px; }
.mn-search {
  background-color: @mn_field; border: 1px solid @mn_field_border; border-radius: 6px;
  min-height: 30px; padding: 0 9px; color: @mn_muted;
}
.mn-search text { color: white; font-size: 13px; }
.mn-search placeholder { color: @mn_muted; }
.mn-search .clear { background-color: #555555; color: black; border-radius: 99px; min-width: 16px; min-height: 16px;
  -gtk-icon-size: 8px; padding: 0; border: none; box-shadow: none; }
.mn-list-header { padding: 10px 18px 14px 18px; border-bottom: 1px solid @mn_divider; }
.mn-list-title { font-family: "Barlow Condensed"; font-weight: 800; font-size: 26px; color: white; }
.mn-list-count { font-size: 12px; color: #999999; }
.mn-scope { background-color: #151515; border: 1px solid #262626; border-radius: 6px; padding: 2px; }
.mn-scope button { background: none; border: none; box-shadow: none; border-radius: 4px; min-height: 24px;
  font-size: 12px; font-weight: 500; color: #BBBBBB; padding: 0 6px; }
.mn-scope button.on { background-color: white; color: black; }
.mn-empty { font-size: 13px; color: @mn_muted; }
listview.mn-notes, listview.mn-notes > row { background: none; padding: 0; }
listview.mn-notes { padding: 6px 8px; }
listview.mn-notes > row { margin-bottom: 2px; outline: none; }
.mn-note-row { padding: 1px; border-radius: 6px; }
.mn-note-row.active { background-image: linear-gradient(135deg, #D4006C, #FF5500 50%, #FFB800); }
.mn-note-row > .inner { padding: 10px 11px; border-radius: 5px; }
.mn-note-row.active > .inner { background-color: #1A1A1A; }
.mn-note-title { font-size: 14px; font-weight: 600; color: white; }
.mn-note-snippet { font-size: 13px; color: @mn_soft; }
.mn-note-meta { font-size: 12px; color: @mn_muted; }
.mn-thumb { border-radius: 4px; border: 1px solid @mn_field_border; }

/* Editor */
.mn-editor-toolbar { min-height: 52px; padding: 0 10px; border-bottom: 1px solid @mn_divider; }
.mn-trash-banner { background-color: #141414; border-bottom: 1px solid @mn_border; padding: 10px 20px; font-size: 13px; color: @mn_icon; }
.mn-footer { min-height: 28px; padding: 0 16px; border-top: 1px solid @mn_divider; font-size: 12px; color: @mn_muted; }
.mn-empty-editor { font-family: "Barlow Condensed"; font-weight: 700; font-size: 22px; letter-spacing: 0.4px; color: #666666; }
.mn-picker { border: 1px solid @mn_field_border; border-radius: 5px; min-height: 28px; padding: 0 8px; font-size: 13px; color: white; }
.mn-picker:hover { background-color: @mn_hover; }
.mn-picker image { color: @mn_icon; }
.mn-picker .chev { color: @mn_muted; -gtk-icon-size: 9px; }

.mn-body.all-selected .mn-block { background-color: alpha(@mn_orange, 0.18); border-radius: 4px; }
.mn-title, .mn-title text { font-family: "Barlow Condensed"; font-weight: 700; font-size: 42px; color: white;
  background: none; caret-color: white; }
.mn-title placeholder { color: #666666; }
text.mn-line, .mn-line text { caret-color: white; }
.mn-line placeholder { color: #666666; }
.mn-line { background: none; }
.mn-line.item { font-size: 16px; color: @mn_text; }
.mn-line.small { font-size: 12px; color: #999999; }
.mn-line.lang { font-size: 11px; color: @mn_muted; }

textview.mn-text, textview.mn-text text { background: none; color: @mn_text; caret-color: white; }
textview.mn-text { font-size: 16px; }
textview.mn-text.heading { font-family: "Barlow Condensed"; font-weight: 600; font-size: 22px; }
textview.mn-text.heading text { color: white; }
textview.mn-text.code { font-family: monospace; font-size: 13px; }
textview.mn-text.code text { color: #F2F2F2; }
textview.mn-text text selection, .mn-line selection, .mn-title selection { background-color: #3A2A20; color: inherit; }
.mn-placeholder { color: #555555; font-size: 16px; }

.mn-bullet { background-color: @mn_text; border-radius: 99px; min-width: 5px; min-height: 5px; }
.mn-code { background-color: #0E0E0E; border: 1px solid #242424; border-radius: 4px; }
.mn-code-header { padding: 7px 12px; border-bottom: 1px solid #1E1E1E; }
.mn-link { border: 1px solid @mn_field_border; border-radius: 4px; padding: 12px 14px; }
.mn-link:hover { border-color: #444444; }
.mn-link-icon { background-color: @mn_field; border-radius: 4px; min-width: 36px; min-height: 36px; color: @mn_orange; }
.mn-link-title { font-size: 14px; font-weight: 600; color: white; }
.mn-hr { background-color: #3A3A3A; min-height: 1px; }
.mn-hr.selected { background-color: @mn_orange; min-height: 2px; }
.mn-image { border-radius: 4px; }
.mn-image.hover { box-shadow: 0 0 0 1px @mn_orange; }
.mn-handle { background-color: @mn_orange; border: 1.5px solid white; border-radius: 2px; min-width: 8px; min-height: 8px; }
.mn-image-missing-label { font-family: monospace; font-size: 12px; color: @mn_muted; background-color: black; padding: 4px 8px; }

/* Popovers y diálogos */
popover.mn-popover > contents { background-color: @mn_popover; border: 1px solid #2C2C2C; padding: 5px; }
popover.mn-popover .mn-nav-row { min-height: 28px; }
.mn-menu-item { border-radius: 5px; padding: 0 9px; min-height: 28px; font-size: 13px; color: #BBBBBB; }
.mn-menu-item:hover { background-color: #1C1C1C; color: white; }
.mn-menu-sep { background-color: #262626; min-height: 1px; margin: 4px 0; }
.mn-dialog-title { font-family: "Barlow Condensed"; font-weight: 800; font-size: 24px; color: white; }
.mn-dialog-subtitle { font-size: 13px; color: @mn_soft; }
.mn-dialog entry, .mn-dialog passwordentry {
  background-color: @mn_field; border: 1px solid @mn_field_border; border-radius: 6px; color: white;
  min-height: 32px; box-shadow: none;
}
.mn-dialog entry:focus-within, .mn-dialog passwordentry:focus-within { border-color: #555555; outline: none; }
.mn-field-label { font-size: 12px; color: @mn_soft; }
.mn-help { font-size: 12px; color: @mn_muted; }
.mn-message { font-size: 13px; color: @mn_soft; }
.mn-dropzone { border: 1.5px dashed #3A3A3A; border-radius: 6px; min-height: 150px; color: #AAAAAA; }
.mn-dropzone.hover { border-color: @mn_orange; color: white; }
.mn-filelist { border: 1px solid @mn_field_border; border-radius: 6px; }
.mn-filelist > box { padding: 10px 14px; border-bottom: 1px solid @mn_border; }
.mn-filename { font-family: monospace; font-size: 12px; }
.mn-check { border: 1.5px solid #666666; border-radius: 4px; min-width: 16px; min-height: 16px; color: black; -gtk-icon-size: 10px; }
.mn-check.on { border-color: transparent; background-image: linear-gradient(135deg, #D4006C, #FF5500 50%, #FFB800); }
progressbar.mn-progress trough { background-color: #262626; border-radius: 99px; min-height: 6px; }
progressbar.mn-progress progress { background-image: linear-gradient(90deg, #D4006C, #FF5500 50%, #FFB800);
  border-radius: 99px; min-height: 6px; border: none; }
.mn-orange { color: @mn_orange; }
.mn-toast { font-size: 12px; color: @mn_muted; }

scrollbar { background: none; border: none; }
scrollbar slider { background-color: #3A3A3A; min-width: 6px; min-height: 6px; }
"""


def register_fonts():
    """Registra Barlow Condensed y DM Sans (licencia OFL) para este proceso, como CTFontManager en macOS."""
    fonts = os.path.join(RESOURCES, "fonts")
    try:
        fc = ctypes.CDLL("libfontconfig.so.1")
        fc.FcConfigAppFontAddDir.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddDir(None, fonts.encode())
    except OSError:
        pass


def install(display: Gdk.Display):
    settings = Gtk.Settings.get_for_display(display)
    # Tema oscuro siempre, como en macOS (GTK ≥ 4.20 usa gtk-interface-color-scheme).
    if settings.find_property("gtk-interface-color-scheme") is not None:
        settings.set_property("gtk-interface-color-scheme", Gtk.InterfaceColorScheme.DARK)
    else:
        settings.set_property("gtk-application-prefer-dark-theme", True)
    # Iconos simbólicos coherentes, sea cual sea el tema del escritorio.
    settings.set_property("gtk-icon-theme-name", "Adwaita")
    Gtk.IconTheme.get_for_display(display).add_search_path(os.path.join(RESOURCES, "icons"))
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
