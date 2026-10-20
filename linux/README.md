# Mis Notas para Linux

Versión nativa para Linux de la app de `macos/`, hecha con **GTK 4 + Python (PyGObject)**. Tiene el mismo
diseño, las mismas funciones y sincroniza con la misma API Laravel (`api/`), así que las notas pasan entre el Mac
y Linux sin conversión.

## Instalación

```sh
./install.sh              # lanzador en ~/.local/bin/misnotas + entrada en el menú de aplicaciones
./install.sh --uninstall  # quita el lanzador (las notas se conservan)
```

Dependencias del sistema (en Omarchy/Arch ya vienen instaladas):
`python-gobject gtk4 libsecret` (Arch) · `python3-gi gir1.2-gtk-4.0 gir1.2-secret-1` (Debian/Ubuntu).

Para probar sin instalar: `python3 -m misnotas` desde esta carpeta.

## Dónde guarda las cosas

| Qué | macOS | Linux |
|---|---|---|
| Base de datos local | `~/Library/Application Support/MisNotas/notas.sqlite` | `~/.local/share/misnotas/notas.sqlite` |
| Imágenes | `…/MisNotas/attachments/` | `~/.local/share/misnotas/attachments/` |
| Servidor | UserDefaults | `~/.config/misnotas/config.json` |
| Token | Llavero | Llavero del sistema (Secret Service: gnome-keyring, KWallet…) |

## Estructura

```
misnotas/
  core/          lógica sin interfaz (traducción de MisNotasCore)
    models.py        notas, libretas, bloques y adjuntos (mismo JSON que la API)
    inline_html.py   HTML de los párrafos (<b> <i> <u> <a> <br>) ↔ tramos con estilo
    enex.py          importación de Evernote (.enex / ENML)
    database.py      réplica SQLite con búsqueda FTS5 y la regla de fusión
    api.py           cliente HTTP de /api/sync y /api/attachments
    sync_engine.py   un ciclo de sincronización
  state.py       estado de la interfaz (AppState)
  sync.py        cuándo sincronizar (SyncCoordinator)
  platform.py    rutas XDG, ajustes y token
  ui/            ventana, barra lateral, lista, editor, bloques, ajustes e importación
tests/           tests del núcleo (traducción de CoreTests.swift)
```

Tests: `python3 -m unittest discover -s tests -t .`

## Atajos de teclado

Los de macOS con **Ctrl** en lugar de ⌘:

| Acción | Atajo |
|---|---|
| Nueva nota / Buscar | Ctrl+N / Ctrl+F |
| Negrita, cursiva, subrayado | Ctrl+B, Ctrl+I, Ctrl+U |
| Enlace | Ctrl+K (Ctrl+clic para editar un enlace del texto) |
| Encabezado, lista, código, imagen | Ctrl+Alt+H, Ctrl+Alt+L, Ctrl+Alt+C, Ctrl+Alt+I |
| Mover a la Papelera / Favorita | Ctrl+Supr / Ctrl+Mayús+F |
| Barra lateral | F9 o Ctrl+Mayús+S |
| Sincronizar / Ajustes | Ctrl+R / Ctrl+, |
| Importar de Evernote | Ctrl+Mayús+I |
| Seleccionar todos los bloques | Ctrl+A dos veces |
| Salir | Ctrl+Q |

En la lista: ↑/↓ para moverse, Ctrl+clic y Mayús+clic para marcar varias notas, arrastrar notas a una libreta.
