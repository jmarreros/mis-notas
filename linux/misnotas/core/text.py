"""Utilidades de texto independientes de la interfaz."""
from __future__ import annotations

import unicodedata


def fold(s: str) -> str:
    """Minúsculas y sin tildes: para comparar como `localizedStandardContains` ("japon" ≈ "Japón")."""
    decomposed = unicodedata.normalize("NFD", s.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def contains(haystack: str, needle: str) -> bool:
    return fold(needle) in fold(haystack)


def find_folded(text: str, term: str, start: int = 0) -> tuple[int, int] | None:
    """Posición (inicio, fin) de `term` en `text` ignorando mayúsculas y tildes, en índices de `text`."""
    if not term:
        return None
    # Mapea cada carácter plegado a su índice original (el plegado puede cambiar longitudes).
    folded, index = [], []
    for i, ch in enumerate(text):
        f = fold(ch)
        folded.append(f)
        index.extend([i] * len(f))
    flat = "".join(folded)
    t = fold(term)
    pos = flat.find(t, sum(len(f) for f in folded[:start]))
    if pos < 0 or not t:
        return None
    first = index[pos]
    last = index[pos + len(t) - 1]
    return first, last + 1
