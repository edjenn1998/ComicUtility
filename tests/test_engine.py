import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import xml.etree.ElementTree as ET

from engine import (
    Book,
    Cancelled,
    image_of,
    metadata_bytes,
    metadata_values,
    safe_name,
    save,
)
from PIL import Image
from pypdf import PdfReader


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        for name, color in [("10.png", "blue"), ("2.png", "green"), ("1.png", "red")]:
            Image.new("RGB", (240, 360), color).save(self.images / name)
        (self.images / "ComicInfo.xml").write_text(
            '<ComicInfo><Series>Test</Series><Unknown>Keep me</Unknown><Pages><Page Image="0" Type="FrontCover"/><Page Image="2" Type="Story"/></Pages></ComicInfo>'
        )
        self.book = Book.load(self.images)

    def tearDown(self):
        self.book.close()
        self.tmp.cleanup()

    def test_natural_order_and_lossless_cbz(self):
        self.assertEqual(
            [e.name for e in self.book.entries if e.image], ["1.png", "2.png", "10.png"]
        )
        out = self.root / "out.cbz"
        save(self.book, self.book.entries, out)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(
                z.read("pages/00001.png"), (self.images / "1.png").read_bytes()
            )
            self.assertIsNone(z.testzip())

    def test_cb7_roundtrip(self):
        out = self.root / "out.cb7"
        save(self.book, self.book.entries, out)
        book = Book.load(out)
        try:
            self.assertEqual(sum(e.image for e in book.entries), 3)
            self.assertEqual(metadata_values(book)["Unknown"], "Keep me")
        finally:
            book.close()

    def test_pdf_and_pdf_to_cbz(self):
        pdf = self.root / "out.pdf"
        save(self.book, self.book.entries, pdf)
        self.assertEqual(len(PdfReader(pdf).pages), 3)
        book = Book.load(pdf)
        try:
            im = image_of(book.entries[0], 72)
            self.assertEqual(im.size, (116, 173))
            im.close()
            out = self.root / "pdf.cbz"
            save(book, book.entries, out, dpi=72)
            with zipfile.ZipFile(out) as z:
                self.assertEqual(len(z.namelist()), 3)
        finally:
            book.close()

    def test_pdf_reorder_retains_pages(self):
        pdf = self.root / "out.pdf"
        save(self.book, self.book.entries, pdf)
        book = Book.load(pdf)
        try:
            # Replacing source must not invalidate the staged PDF input.
            pdf.write_bytes(b"changed externally")
            out = self.root / "edited.pdf"
            save(book, [book.entries[2], book.entries[0]], out)
            self.assertEqual(len(PdfReader(out).pages), 2)
        finally:
            book.close()

    def test_metadata_reorder_and_cover(self):
        entries = [e for e in self.book.entries if e.image]
        reordered = [entries[2], entries[0]]
        root = ET.fromstring(
            metadata_bytes(self.book, reordered, {"Title": "Edited"}, entries[2])
        )
        self.assertEqual(root.findtext("Unknown"), "Keep me")
        self.assertEqual(root.findtext("PageCount"), "2")
        self.assertEqual(root.find('Pages/Page[@Type="FrontCover"]').get("Image"), "0")

    def test_no_clobber_and_cancel(self):
        out = self.root / "existing.cbz"
        out.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            save(self.book, self.book.entries, out)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            save(self.book, self.book.entries, out, overwrite=True, cancel=cancel)
        self.assertEqual(out.read_bytes(), b"original")
        self.assertFalse(list(self.root.glob(".comic-writing-*")))

    def test_cancel_mid_conversion(self):
        out = self.root / "cancel.cbz"
        cancel = threading.Event()

        def progress(a, b, c):
            cancel.set()

        with self.assertRaises(Cancelled):
            save(self.book, self.book.entries, out, cancel=cancel, progress=progress)
        self.assertFalse(out.exists())

    def test_atomic_overwrite(self):
        out = self.root / "out.cbz"
        out.write_bytes(b"old")
        save(self.book, self.book.entries, out, overwrite=True)
        with zipfile.ZipFile(out) as z:
            self.assertIsNone(z.testzip())

    def test_traversal_and_duplicate_rejected(self):
        for name in ["../bad", "/bad", "C:\\bad", "folder/../../bad"]:
            with self.assertRaises(ValueError):
                safe_name(name)
        out = self.root / "unsafe.cbz"
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("../outside.png", b"bad")
        with self.assertRaises(ValueError):
            Book.load(out)

    def test_remove_add_image(self):
        entries = [e for e in self.book.entries if e.image][1:]
        added = self.book.add([self.images / "1.png"])
        entries += added
        out = self.root / "edited.cbz"
        save(self.book, entries, out)
        b = Book.load(out)
        try:
            self.assertEqual(sum(e.image for e in b.entries), 3)
        finally:
            b.close()

    def test_corrupt_page_does_not_replace_output(self):
        page = next(e for e in self.book.entries if e.image)
        page.path.write_bytes(b"invalid")
        out = self.root / "protected.cbz"
        out.write_bytes(b"old")
        with self.assertRaises(Exception):
            save(self.book, self.book.entries, out, overwrite=True)
        self.assertEqual(out.read_bytes(), b"old")

    def test_no_empty_comic(self):
        with self.assertRaises(ValueError):
            save(self.book, [], self.root / "empty.cbz")


if __name__ == "__main__":
    unittest.main()
