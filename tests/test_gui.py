import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Book
from gui import STYLE, Window
from PIL import Image
from PySide6.QtWidgets import QApplication, QFileDialog


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        folder = self.root / "pages"
        folder.mkdir()
        for i in range(3):
            Image.new("RGB", (100, 200), (i * 60, 0, 0)).save(folder / f"{i + 1}.png")
        self.window = Window()
        self.window.show()
        self.window.loaded(Book.load(folder))
        self.app.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        self.temp.cleanup()
        self.app.processEvents()

    def test_remove_undo_and_cover(self):
        w = self.window
        w.list.setCurrentRow(1)
        w.remove()
        self.assertEqual(len(w.entries), 2)
        w.undo()
        self.assertEqual(len(w.entries), 3)
        w.list.setCurrentRow(2)
        entry = w.current()
        w.make_cover()
        self.assertIs(w.entries[0], entry)
        self.assertIs(w.cover, entry)
        w.undo()
        self.assertIsNone(w.cover)

    def test_add_replace_and_save_worker(self):
        w = self.window
        img = self.root / "added.png"
        Image.new("RGB", (30, 50), "green").save(img)
        with patch.object(
            QFileDialog, "getOpenFileNames", return_value=([str(img)], "")
        ):
            w.add()
        self.assertEqual(len(w.entries), 4)
        w.list.setCurrentRow(0)
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(img), "")):
            w.replace()
        out = self.root / "saved.cbz"
        with patch.object(QFileDialog, "getSaveFileName", return_value=(str(out), "")):
            w.save_as()
        self.wait()
        self.assertTrue(out.exists())
        self.assertFalse(w.dirty)

    def test_batch_existing_and_conversion(self):
        w = self.window
        source = self.root / "input.cbz"
        from engine import save

        save(w.book, w.entries, source)
        out = self.root / "output"
        out.mkdir()
        w.enqueue([str(source)])
        w.destination.setText(str(out))
        w.batch_run()
        self.wait()
        self.assertTrue((out / "input.cbz").exists())
        self.assertIn("Saved:", w.batchlist.item(0).text())
        w.batch_run()
        self.wait()
        self.assertIn("Skipped:", w.batchlist.item(0).text())

    def test_minimum_size_controls_visible(self):
        w = self.window
        w.resize(980, 700)
        self.app.processEvents()
        self.assertTrue(w.savebtn.isVisible())
        self.assertLessEqual(w.savebtn.geometry().right(), w.editor.width())
        self.assertLessEqual(
            w.savebtn.mapTo(w.centralWidget(), w.savebtn.rect().bottomRight()).y(),
            w.centralWidget().height(),
        )

    def wait(self):
        deadline = time.monotonic() + 10
        while self.window.task and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.window.task)


if __name__ == "__main__":
    unittest.main()
