"""Actual RAR3/RAR5 fixtures from the libarchive project's regression suite."""

import unittest
from pathlib import Path

import libarchive


class RarTests(unittest.TestCase):
    def test_rar3(self):
        with libarchive.file_reader(
            str(Path(__file__).parent / "fixtures/test_read_format_rar.rar")
        ) as archive:
            contents = {e.pathname: b"".join(e.get_blocks()) for e in archive}
        self.assertEqual(contents["test.txt"], b"test text document\r\n")

    def test_rar5_compressed_and_solid(self):
        for name, count in [
            ("test_read_format_rar5_compressed.rar", 1),
            ("test_read_format_rar5_multiple_files_solid.rar", 4),
        ]:
            with libarchive.file_reader(
                str(Path(__file__).parent / "fixtures" / name)
            ) as archive:
                contents = [b"".join(e.get_blocks()) for e in archive]
            self.assertEqual(len(contents), count)
            self.assertTrue(all(contents))


class RarComicConversionTests(unittest.TestCase):
    def test_stored_rar_comic_to_cbz(self):
        # A minimal RAR4 stored-file fixture: fixed headers plus independent PNGs.
        import io
        import struct
        import sys
        import tempfile
        import zlib

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from engine import Book, save
        from PIL import Image

        def header(kind, flags, body):
            content = struct.pack("<BHH", kind, flags, 7 + len(body)) + body
            return struct.pack("<H", zlib.crc32(content) & 0xFFFF) + content

        data = bytearray(b"Rar!\x1a\x07\x00")
        data += header(0x73, 0, b"\0" * 6)
        for i, color in enumerate(["red", "green", "blue"]):
            buffer = io.BytesIO()
            Image.new("RGB", (24, 36), color).save(buffer, "PNG")
            image = buffer.getvalue()
            name = f"{i + 1}.png".encode()
            body = (
                struct.pack(
                    "<IIBIIBBHI",
                    len(image),
                    len(image),
                    3,
                    zlib.crc32(image),
                    0,
                    20,
                    0x30,
                    len(name),
                    0o100644,
                )
                + name
            )
            data += header(0x74, 0x8000, body) + image
        data += header(0x7B, 0, b"")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "comic.cbr"
            source.write_bytes(data)
            book = Book.load(source)
            try:
                self.assertEqual(sum(e.image for e in book.entries), 3)
                output = Path(folder) / "comic.cbz"
                save(book, book.entries, output)
                result = Book.load(output)
                try:
                    self.assertEqual(sum(e.image for e in result.entries), 3)
                finally:
                    result.close()
            finally:
                book.close()
