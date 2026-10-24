import io
import os
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
from engine import Book, Cancelled, Entry, extract, metadata_bytes, save
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        folder = self.root / "pages"
        folder.mkdir()
        for i in range(2):
            Image.new("RGB", (40, 60), "red").save(folder / f"{i}.png")
        self.book = Book.load(folder)

    def tearDown(self):
        self.book.close()
        self.temp.cleanup()

    def test_truncated_jpeg_rejected_on_add_and_save(self):
        buffer = io.BytesIO()
        Image.new("RGB", (100, 200), "red").save(buffer, "JPEG")
        path = self.root / "bad.jpg"
        path.write_bytes(buffer.getvalue()[:-100])
        before = self.book.usage()
        with self.assertRaises(OSError):
            self.book.add([path])
        self.assertEqual(self.book.usage(), before)
        entry = self.book.stage(path.name, source=path)
        out = self.root / "protected.cbz"
        out.write_bytes(b"original")
        with self.assertRaises(OSError):
            save(self.book, [entry], out, overwrite=True)
        self.assertEqual(out.read_bytes(), b"original")

    def test_all_animation_frames_decoded(self):
        path = self.root / "animation.gif"
        frames = [Image.new("RGB", (20, 20), c) for c in ("red", "blue")]
        frames[0].save(path, save_all=True, append_images=frames[1:])
        for im in frames:
            im.close()
        original = Image.Image.load
        visited = []

        def load(im, *a, **kw):
            if im.format == "GIF":
                visited.append(im.tell())
            return original(im, *a, **kw)

        with patch.object(Image.Image, "load", load):
            engine.validate_image(path)
        self.assertIn(1, visited)

    def test_transaction_limits_and_pruning(self):
        note = self.root / "note.txt"
        note.write_text("note")
        original = self.book.usage()
        with patch.object(engine, "MAX_BYTES", original[1] + 3):
            with self.assertRaises(ValueError):
                self.book.add([note])
        with patch.object(engine, "MAX_FILES", len(self.book.entries)):
            with self.assertRaises(ValueError):
                self.book.add([note])
        missing = self.root / "missing.txt"
        with self.assertRaises(ValueError):
            self.book.add([note, missing])
        self.assertEqual(self.book.usage(), original)
        added = self.book.add([note])
        self.book.entries.extend(added)
        second = self.book.add([note])
        self.assertEqual(second[0].name, "note_2.txt")
        self.book.prune(self.book.entries)
        self.assertFalse(second[0].path.exists())

    def test_pdf_cancel_and_size_limits(self):
        path = self.root / "source.pdf"
        save(self.book, self.book.entries, path)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            Book.load(path, cancel)
        with patch.object(engine, "MAX_ENTRY", 10):
            with self.assertRaises(ValueError):
                Book.load(path)

        def progress(*args):
            cancel.set()

        cancel.clear()
        with self.assertRaises(Cancelled):
            Book.load(path, cancel, progress)

    def test_metadata_original_bytes_and_comments(self):
        xml = b'<?xml version="1.0"?><ComicInfo><!-- keep --><Unknown a="b">yes</Unknown><Pages><!-- page note --><Page Image="0"/></Pages></ComicInfo>'
        self.book.metadata = xml
        self.assertEqual(metadata_bytes(self.book, self.book.entries), xml)
        changed = metadata_bytes(self.book, list(reversed(self.book.entries)), {"Title": "New"})
        self.assertIn(b"<!-- keep -->", changed)
        self.assertIn(b"<!-- page note -->", changed)
        self.assertIn(b'<Unknown a="b">yes</Unknown>', changed)

    def test_xml_entities_rejected_when_editing(self):
        self.book.metadata = b'<!DOCTYPE ComicInfo [<!ENTITY x "expanded">]><ComicInfo><Title>&x;</Title></ComicInfo>'
        with self.assertRaises(Exception):
            metadata_bytes(self.book, self.book.entries, {"Title": "New"})

    def test_duplicate_link_and_special_archive_entries(self):
        path = self.root / "duplicates.cbz"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("page.png", b"one")
                z.writestr("PAGE.png", b"two")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            Book.load(path)
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            path = self.root / "special.tar"
            with tarfile.open(path, "w") as t:
                member = tarfile.TarInfo("page.png")
                member.type = kind
                member.linkname = "/etc/passwd"
                t.addfile(member)
            with self.assertRaisesRegex(ValueError, "link or special"):
                Book.load(path)

    def test_extraction_preflight_folders_and_rollback(self):
        selected = [Entry("a/page.png", self.book.entries[0].path),
                    Entry("b/page.png", self.book.entries[1].path)]
        dest = self.root / "extract"
        with self.assertRaisesRegex(ValueError, "collide"):
            extract(self.book, selected, selected, dest, preserve_folders=False)
        self.assertFalse(dest.exists())
        outputs = extract(self.book, selected, selected, dest)
        self.assertEqual(len(outputs), 2)
        with self.assertRaises(FileExistsError):
            extract(self.book, selected, selected, dest)
        cancel = threading.Event()
        dest2 = self.root / "cancelled"
        with self.assertRaises(Cancelled):
            extract(self.book, selected, selected, dest2, cancel=cancel,
                    progress=lambda *a: cancel.set())
        self.assertFalse(any(p.is_file() for p in dest2.rglob("*")))
        outside = self.root / "outside"
        outside.mkdir()
        (dest / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            extract(self.book, selected, [Entry("link/page.png", selected[0].path)], dest)

    def test_pdf_reorder_preserves_searchable_text(self):
        source = self.root / "text.pdf"
        c = canvas.Canvas(str(source))
        for text in ("First page searchable", "Second page searchable"):
            c.drawString(40, 600, text)
            c.showPage()
        c.save()
        book = Book.load(source)
        try:
            out = self.root / "reordered.pdf"
            save(book, list(reversed(book.entries)), out)
            reader = PdfReader(out)
            self.assertIn("Second page searchable", reader.pages[0].extract_text())
            self.assertIn("First page searchable", reader.pages[1].extract_text())
        finally:
            book.close()


from gui import Window
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


class EditorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        folder = self.root / "pages"
        folder.mkdir()
        Image.new("CMYK", (400, 600), (0, 100, 0, 0)).save(folder / "1.jpg")
        Image.new("RGB", (40, 60), "blue").save(folder / "2.png")
        self.w = Window()
        self.w.loaded(Book.load(folder))

    def tearDown(self):
        if self.w.task:
            self.w.cancel()
            self.wait()
        self.w.dirty = False
        self.w.close()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 10
        while (self.w.task or self.w.preview_task) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(self.w.task)
        self.assertIsNone(self.w.preview_task)

    def test_cmyk_async_preview_and_tiny_thumbnail(self):
        self.wait()
        self.assertIsNotNone(self.w.previewpix)
        icon = self.w.previewcache[id(self.w.current())]
        self.assertTrue(all(s.width() <= 48 and s.height() <= 64 for s in icon.availableSizes()))

    def test_repeated_add_undo_redo_saved_state(self):
        note = self.root / "notes.txt"
        note.write_text("hello")
        self.w.add_paths([str(note)])
        self.wait()
        self.w.add_paths([str(note)])
        self.wait()
        self.assertEqual(sorted(e.name for e in self.w.entries if not e.image), ["notes.txt", "notes_2.txt"])
        out = self.root / "edited.cbz"
        save(self.w.book, self.w.entries, out)
        self.w.saved(out)
        self.assertFalse(self.w.dirty)
        self.w.undo()
        self.assertTrue(self.w.dirty)
        self.w.redo()
        self.assertFalse(self.w.dirty)
        self.assertEqual(self.w.book.source, out)

    def test_stale_preview_is_ignored_and_event_loop_stays_responsive(self):
        self.w.stop_preview()
        original = engine.image_of
        entered = threading.Event()
        release = threading.Event()

        def slow(*args):
            entered.set()
            release.wait(3)
            return original(*args)

        with patch("gui.image_of", slow):
            self.w.preview()
            self.assertTrue(entered.wait(3))
            tick = []
            QTimer.singleShot(0, lambda: tick.append(True))
            self.app.processEvents()
            self.assertEqual(tick, [True])
            self.w.list.setCurrentRow(1)
            release.set()
            self.wait()
        self.assertTrue(self.w.pageinfo.text().startswith("2.png"))

    def test_selection_and_cover_metadata_entry(self):
        self.w.list.item(1).setSelected(True)
        self.assertEqual(len(self.w.selected()), 2)
        self.w.refresh()
        self.assertEqual(len(self.w.selected()), 2)
        self.w.make_cover()
        self.assertTrue(any(e.name == "ComicInfo.xml" for e in self.w.entries))
        self.w.undo()
        self.assertFalse(self.w.dirty)

    def test_thumbnail_cache_stays_bounded_while_browsing(self):
        self.w.stop_preview()
        path = self.w.entries[1].path
        self.w.entries = [Entry(f"{i}.png", path) for i in range(260)]
        self.w.refresh()
        for i in range(260):
            self.w.list.setCurrentRow(i)
            self.wait()
        self.assertEqual(len(self.w.previewcache), 256)
        self.assertTrue(self.w.list.item(0).icon().isNull())

    def test_generated_metadata_extracts_and_can_be_removed(self):
        self.w.make_cover()
        entry = next(e for e in self.w.entries if e.name == "ComicInfo.xml")
        outputs = extract(self.w.book, self.w.entries, [entry], self.root / "xml", cover=self.w.cover)
        self.assertIn(b'FrontCover', outputs[0].read_bytes())
        self.w.allfiles.setChecked(True)
        for i in range(self.w.list.count()):
            if self.w.list.item(i).data(256) is entry:
                self.w.list.setCurrentRow(i)
                break
        self.w.remove()
        self.assertIsNone(self.w.cover)
        self.assertIsNone(metadata_bytes(self.w.book, self.w.entries, self.w.updates, self.w.cover))
