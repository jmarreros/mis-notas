"""Tests del núcleo: traducción de macos/Tests/MisNotasTests/CoreTests.swift.

Ejecutar: python3 -m unittest discover -s tests   (desde linux/)
"""
import json
import os
import shutil
import tempfile
import unittest

from misnotas.core import inline_html
from misnotas.core.api import PullResponse
from misnotas.core.database import AppDatabase, NotesRepository
from misnotas.core.enex import enml_to_blocks, parse_file
from misnotas.core.models import Attachment, Block, Note, Notebook, TodoItem, now_ms
from misnotas.core.sync_engine import SyncEngine, SyncResult

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class EnexTests(unittest.TestCase):
    def test_parses_sample_export(self):
        notes = parse_file(os.path.join(FIXTURES, "muestra.enex"))
        self.assertEqual(len(notes), 2)

        n = notes[0]
        self.assertEqual(n.title, "Viaje a Asturias")
        self.assertEqual(n.created, 1_755_250_200_000)
        self.assertIsNotNone(n.updated)

        self.assertEqual([b.type for b in n.blocks], ["p", "h", "todo", "p", "code", "p", "todo"])
        self.assertEqual(n.blocks[0].html, 'Ruta del <b>Cares</b> en un día, salir desde Poncebos.<br>'
                                           'Ver <a href="https://example.com/cares?a=1&amp;b=2">mapa</a>.')
        self.assertEqual(n.blocks[1].html, "Equipaje")
        self.assertEqual(n.blocks[2].items, [TodoItem("Botas", True), TodoItem("Chubasquero", False)])
        self.assertEqual(n.blocks[3].html, "Después del todo.")
        self.assertEqual(n.blocks[4].text, "ssh nas.local\n  ls -la")
        self.assertEqual(n.blocks[5].html, "• uno<br>• dos")
        self.assertEqual(n.blocks[6].items, [TodoItem("Hecho v10", True), TodoItem("Pendiente v10", False)])

        self.assertEqual([(b.type, b.html) for b in notes[1].blocks], [("p", "")])
        self.assertIsNone(notes[1].updated)

    def test_empty_enml(self):
        self.assertEqual([b.type for b in enml_to_blocks("")], ["p"])


class InlineHTMLTests(unittest.TestCase):
    def test_round_trip(self):
        html = ('Hola <b>mundo <i>feliz</i></b> y <u>sub</u><br>línea '
                '<a href="https://a.com/?x=1&amp;y=2">enlace</a> &lt;3')
        runs = inline_html.parse(html)
        self.assertEqual("".join(r.text for r in runs), "Hola mundo feliz y sub\nlínea enlace <3")
        out = inline_html.html_from_runs(runs)
        self.assertEqual(out, 'Hola <b>mundo </b><b><i>feliz</i></b> y <u>sub</u><br>línea '
                              '<a href="https://a.com/?x=1&amp;y=2">enlace</a> &lt;3')
        # Una segunda vuelta es estable.
        self.assertEqual(inline_html.html_from_runs(inline_html.parse(out)), out)

    def test_divs_become_lines(self):
        self.assertEqual("".join(r.text for r in inline_html.parse("<div>a</div><div><br></div><div>b</div>")), "a\n\nb")
        self.assertEqual(inline_html.plain_text("Uno&nbsp;<b>dos</b>\n tres"), "Uno dos  tres")


class FakeServer:
    """Servidor en memoria que imita la API Laravel (rev global + last-write-wins)."""

    def __init__(self):
        self.rev = 0
        self.notebooks: dict = {}
        self.notes: dict = {}
        self.uploads: dict = {}

    def pull(self, since):
        nbs = sorted((v for v in self.notebooks.values() if v[1] > since), key=lambda v: v[1])
        ns = sorted((v for v in self.notes.values() if v[1] > since), key=lambda v: v[1])
        # Copias, como si viajaran por la red.
        return PullResponse(self.rev, [Notebook.from_json(v[0].to_json()) for v in nbs],
                            [Note.from_json(v[0].to_json()) for v in ns])

    def push(self, notebooks, notes):
        rejected = PullResponse(0, [], [])
        for nb in notebooks:
            ex = self.notebooks.get(nb.id)
            if ex and ex[0].updated_at > nb.updated_at:
                rejected.notebooks.append(Notebook.from_json(ex[0].to_json()))
                continue
            nb = Notebook.from_json(nb.to_json()); nb.dirty = False
            self.rev += 1; self.notebooks[nb.id] = (nb, self.rev)
        for n in notes:
            ex = self.notes.get(n.id)
            if ex and (ex[0].updated_at > n.updated_at or (ex[0].deleted_at is not None and n.deleted_at is None)):
                rejected.notes.append(Note.from_json(ex[0].to_json()))
                continue
            n = Note.from_json(n.to_json()); n.dirty = False
            self.rev += 1; self.notes[n.id] = (n, self.rev)
        rejected.rev = self.rev
        return rejected

    def upload(self, attachment, data):
        self.uploads[attachment.id] = data

    def download(self, attachment_id):
        return self.uploads.get(attachment_id, b"")


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mn-tests-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, server):
        db = AppDatabase()
        self.addCleanup(db.close)
        repo = NotesRepository(db)
        return repo, SyncEngine(repo, server, self.tmp)

    def test_two_devices_converge(self):
        server = FakeServer()
        a, sync_a = self.client(server)
        b, sync_b = self.client(server)

        nb = a.save_notebook(Notebook(name="Viajes"))
        note = a.save_note(Note(notebook_id=nb.id, title="Kioto", blocks=[Block.paragraph("ryokan")]))
        self.assertEqual(sync_a.sync(), SyncResult(pushed=2, pulled=0))
        self.assertEqual(a.dirty_records()[1], [])

        sync_b.sync()
        self.assertEqual([n.title for n in b.notes()], ["Kioto"])
        self.assertEqual([n.name for n in b.notebooks()], ["Viajes"])
        self.assertEqual(b.search("kioto"), {note.id})
        self.assertEqual(b.search("RYOK"), {note.id})

        # B edita, A recibe.
        on_b = b.note(note.id)
        on_b.title = "Kioto y Nara"
        b.save_note(on_b)
        sync_b.sync()
        sync_a.sync()
        note = a.note(note.id)
        self.assertEqual(note.title, "Kioto y Nara")
        self.assertFalse(note.dirty)

    def test_local_pending_edit_is_not_overwritten_by_older_remote(self):
        server = FakeServer()
        a, sync_a = self.client(server)
        b, sync_b = self.client(server)
        note = a.save_note(Note(notebook_id=None, title="v1"))
        sync_a.sync()
        sync_b.sync()

        # A edita primero (más antiguo), B después (más reciente) y sincroniza antes.
        on_a = a.note(note.id); on_a.title = "de A"; on_a.updated_at = now_ms() + 10_000
        a.save_note(on_a, touch=False)
        on_b = b.note(note.id); on_b.title = "de B"; on_b.updated_at = now_ms() + 20_000
        b.save_note(on_b, touch=False)

        sync_b.sync()
        sync_a.sync()  # A pierde: el servidor rechaza y A adopta la de B.
        self.assertEqual(a.note(note.id).title, "de B")
        self.assertEqual(a.dirty_records()[1], [])

    def test_newer_local_survives_older_remote(self):
        db = AppDatabase()
        self.addCleanup(db.close)
        a = NotesRepository(db)
        note = a.save_note(Note(notebook_id=None, title="v1"))
        on_b = note.copy(title="remoto", updated_at=now_ms() + 10_000, dirty=False)
        newer = note.copy(title="local", updated_at=now_ms() + 30_000)
        a.save_note(newer, touch=False)
        a.apply_remote([], [on_b], None)
        self.assertEqual(a.note(note.id).title, "local")

    def test_deletions_propagate(self):
        server = FakeServer()
        a, sync_a = self.client(server)
        b, sync_b = self.client(server)
        note = a.save_note(Note(notebook_id=None, title="borrar"))
        sync_a.sync(); sync_b.sync()
        a.delete_forever(note)
        sync_a.sync(); sync_b.sync()
        self.assertEqual(b.notes(), [])
        self.assertEqual(b.search("borrar"), set())

    def test_notebook_order_syncs(self):
        server = FakeServer()
        a, sync_a = self.client(server)
        b, sync_b = self.client(server)
        x = a.save_notebook(Notebook(name="A"))
        y = a.save_notebook(Notebook(name="B"))
        z = a.save_notebook(Notebook(name="C"))
        self.assertEqual([n.name for n in a.notebooks()], ["A", "B", "C"])

        a.reorder_notebooks([z.id, x.id, y.id])
        self.assertEqual([n.name for n in a.notebooks()], ["C", "A", "B"])

        sync_a.sync(); sync_b.sync()
        self.assertEqual([n.name for n in b.notebooks()], ["C", "A", "B"])

    def test_attachments_upload_before_push(self):
        server = FakeServer()
        a, sync_a = self.client(server)
        with open(os.path.join(self.tmp, "x.png"), "wb") as f:
            f.write(bytes([1, 2, 3]))
        a.insert_attachment(Attachment(id="att1", note_id=None, file_name="x.png", mime="image/png", uploaded=False))
        sync_a.sync()
        self.assertEqual(server.uploads["att1"], bytes([1, 2, 3]))
        self.assertEqual(a.pending_uploads(), [])

    def test_server_json_shape(self):
        # El JSON que produce Laravel (snake_case, rev, campos extra) se decodifica bien.
        raw = """
        {"rev":3,"notebooks":[{"id":"nb1","name":"Viajes","sort":0,"created_at":1,"updated_at":2,"deleted_at":null,"rev":1}],
         "notes":[{"id":"n1","notebook_id":"nb1","title":"T","blocks":[{"id":"b","type":"img","attachment_id":"a1","caption":"c"}],
                   "tags":["x"],"created_at":1,"updated_at":2,"trashed_at":null,"deleted_at":null,"rev":3}]}
        """
        r = PullResponse.from_json(json.loads(raw))
        self.assertEqual(r.notes[0].blocks[0].attachment_id, "a1")
        self.assertEqual(r.notes[0].notebook_id, "nb1")
        self.assertFalse(r.notes[0].dirty)

        out = json.dumps(r.notes[0].to_json())
        self.assertIn('"attachment_id": "a1"', out)
        self.assertIn('"notebook_id": "nb1"', out)


if __name__ == "__main__":
    unittest.main()
