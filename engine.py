"""Staged comic editing and verified, atomic output."""

from __future__ import annotations

import ctypes
import errno
import io
import os
import re
import shutil
import sys
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from defusedxml import ElementTree as SafeET
from PIL import Image, ImageOps

if getattr(sys, "frozen", False):
    os.environ["LIBARCHIVE"] = str(Path(sys._MEIPASS) / "libarchive.so.13")
import libarchive
import py7zr
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from version import VERSION

FORMATS = {".cbz", ".zip", ".cbr", ".rar", ".cb7", ".7z", ".pdf"}
IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
MAX_BYTES = 32 * 1024**3
MAX_ENTRY = 2 * 1024**3
MAX_FILES = 50000
MAX_METADATA = 16 * 1024**2
PDF_LOCK = threading.RLock()


class Cancelled(Exception):
    pass


def check(cancel):
    if cancel and cancel.is_set():
        raise Cancelled("Cancelled; no output was committed.")


def natural(s):
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", s)]


def safe_name(name):
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if (
        not name
        or "\x00" in name
        or path.is_absolute()
        or ".." in path.parts
        or str(path) == "."
        or re.match(r"^[A-Za-z]:", name)
    ):
        raise ValueError(f"Unsafe archive filename: {name!r}")
    return str(path)


@dataclass
class Entry:
    name: str
    path: Path | None = None
    pdf: Path | None = None
    page: int | None = None
    original_index: int | None = None

    @property
    def image(self):
        return self.pdf is not None or Path(self.name).suffix.lower() in IMAGES


class Book:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="comic-utility-")
        self.root = Path(self.temp.name)
        self.entries = []
        self.source = None
        self.metadata = None
        self.original_order = ()
        self._staged = {}
        self._bytes = 0

    def close(self):
        self.temp.cleanup()

    def usage(self):
        return len(self._staged), self._bytes

    def register(self, path):
        size = path.stat().st_size
        self._staged[path] = size
        self._bytes += size

    def discard(self, path):
        self._bytes -= self._staged.pop(path, 0)
        path.unlink(missing_ok=True)

    def prune(self, retained):
        """Release files no longer referenced by the document or undo/redo history."""
        keep = {p for e in retained for p in (e.path, e.pdf) if p}
        for p in list(self._staged):
            if p not in keep:
                self.discard(p)

    def stage(self, name, data=None, source=None, cancel=None):
        name = safe_name(name)
        target = self.root / uuid.uuid4().hex
        count, used = self.usage()
        if count >= MAX_FILES:
            raise ValueError("Workspace exceeds the file-count limit (including undo history).")
        try:
            with target.open("wb") as out:
                if source:
                    with Path(source).open("rb") as src:
                        copy_limited(src, out, min(MAX_ENTRY, MAX_BYTES - used), cancel)
                else:
                    if len(data) > min(MAX_ENTRY, MAX_BYTES - used):
                        raise ValueError("Workspace size limit exceeded.")
                    out.write(data)
            self.register(target)
            return Entry(name, target)
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, source, cancel=None, progress=None):
        self = cls()
        self.source = Path(source)
        try:
            check(cancel)
            if self.source.is_dir():
                files = []
                for count, p in enumerate(self.source.rglob("*"), 1):
                    check(cancel)
                    if count > MAX_FILES:
                        raise ValueError("Too many input entries.")
                    if p.is_file() and not p.is_symlink():
                        files.append(p)
                files.sort(key=lambda p: natural(str(p.relative_to(self.source))))
                total = 0
                for i, p in enumerate(files):
                    check(cancel)
                    total += p.stat().st_size
                    if (
                        i >= MAX_FILES
                        or total > MAX_BYTES
                        or p.stat().st_size > MAX_ENTRY
                    ):
                        raise ValueError(
                            "Input exceeds limits: 50,000 files / 32 GiB total / 2 GiB per file."
                        )
                    self.entries.append(
                        self.stage(str(p.relative_to(self.source)), source=p, cancel=cancel)
                    )
                    if progress:
                        progress(i + 1, len(files), p.name)
            elif self.source.suffix.lower() == ".pdf":
                staged_pdf = self.stage("source.pdf", source=self.source, cancel=cancel).path
                check(cancel)
                reader = PdfReader(staged_pdf)
                if reader.is_encrypted:
                    raise ValueError(
                        "Password-protected PDFs are not supported. Open an unlocked copy."
                    )
                if len(reader.pages) > MAX_FILES:
                    raise ValueError("Too many PDF pages.")
                for i in range(len(reader.pages)):
                    check(cancel)
                    self.entries.append(Entry(f"{i + 1:05d}.jpg", pdf=staged_pdf, page=i, original_index=i))
                    if progress:
                        progress(i + 1, len(reader.pages), f"PDF page {i + 1}")
            else:
                total = 0
                seen = set()
                with libarchive.file_reader(str(self.source)) as archive:
                    for count, item in enumerate(archive, 1):
                        check(cancel)
                        if count > MAX_FILES:
                            raise ValueError("Too many archive entries.")
                        if item.islnk or item.issym:
                            raise ValueError("Archive contains a link or special file; only regular files are supported.")
                        if item.isdir:
                            continue
                        if not item.isfile:
                            raise ValueError(
                                "Archive contains a link or special file; only regular files are supported."
                            )
                        name = safe_name(item.pathname)
                        if name.casefold() in seen:
                            raise ValueError(f"Duplicate archive entry: {name}")
                        seen.add(name.casefold())
                        if len(seen) > MAX_FILES:
                            raise ValueError("Too many archive entries.")
                        out = self.root / uuid.uuid4().hex
                        size = 0
                        with out.open("wb") as f:
                            for block in item.get_blocks():
                                check(cancel)
                                size += len(block)
                                total += len(block)
                                if size > MAX_ENTRY or total > MAX_BYTES:
                                    raise ValueError(
                                        "Archive exceeds workspace size limits."
                                    )
                                f.write(block)
                        self.register(out)
                        self.entries.append(Entry(name, out))
                        if progress:
                            progress(len(self.entries), 0, name)
            self.entries.sort(key=lambda e: natural(e.name))
            index = 0
            for e in self.entries:
                if e.image:
                    e.original_index = index
                    index += 1
                if Path(e.name).name.casefold() == "comicinfo.xml":
                    if self.metadata is not None:
                        raise ValueError(
                            "Multiple ComicInfo.xml files found; metadata is ambiguous."
                        )
                    if e.path.stat().st_size > MAX_METADATA:
                        raise ValueError("ComicInfo.xml exceeds the 16 MiB metadata limit.")
                    self.metadata = e.path.read_bytes()
            if not any(e.image for e in self.entries):
                raise ValueError("No supported comic pages found.")
            self.original_order = tuple(e.original_index for e in self.entries if e.image)
            check(cancel)
            return self
        except BaseException:
            self.close()
            raise

    def add(self, paths, cancel=None, progress=None):
        existing = {e.name.casefold() for e in self.entries}
        result = []
        try:
            if len(self.entries) + len(paths) > MAX_FILES:
                raise ValueError("Too many document entries.")
            for i, path in enumerate(paths):
                check(cancel)
                p = Path(path)
                name = p.name
                if name.casefold() == "comicinfo.xml":
                    raise ValueError("Use Metadata to edit ComicInfo.xml.")
                if not p.is_file():
                    raise ValueError(f"Not a regular file: {p}")
                if name.casefold() in existing:
                    n = 2
                    while name.casefold() in existing:
                        name = f"{p.stem}_{n}{p.suffix}"
                        n += 1
                existing.add(name.casefold())
                entry = self.stage(name, source=p, cancel=cancel)
                result.append(entry)
                if entry.image:
                    validate_image(entry.path, cancel)
                if progress:
                    progress(i + 1, len(paths), name)
            check(cancel)
            return result
        except BaseException:
            for e in result:
                self.discard(e.path)
            raise


def copy_limited(src, out, limit, cancel=None):
    size = 0
    while True:
        check(cancel)
        block = src.read(1024 * 1024)
        if not block:
            break
        size += len(block)
        if size > limit:
            raise ValueError("Workspace exceeds 32 GiB total / 2 GiB per file (including undo history).")
        out.write(block)


def validate_image(path, cancel=None):
    """Check container integrity and fully decode every frame, not just headers."""
    check(cancel)
    with Image.open(path) as im:
        im.verify()
    with Image.open(path) as im:
        frame = 0
        while True:
            check(cancel)
            try:
                im.seek(frame)
            except EOFError:
                break
            im.load()
            frame += 1


def display_image(im):
    """Return a Qt/PNG-safe image without changing the original staged bytes."""
    return im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")


def image_of(entry, dpi=150, preview=False):
    if entry.pdf:
        with PDF_LOCK:
            doc = pdfium.PdfDocument(entry.pdf)
            try:
                page = doc[entry.page]
                try:
                    w, h = page.get_size()
                    scale = dpi / 72
                    if preview:
                        scale = min(scale, 1200 / max(w, h))
                    if w * h * scale * scale > 100_000_000:
                        raise ValueError(
                            "PDF page is too large at this resolution; choose a lower DPI."
                        )
                    bitmap = page.render(scale=scale)
                    try:
                        return bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                doc.close()
    with Image.open(entry.path) as im:
        if preview:
            im.thumbnail((1600, 1600))
        with ImageOps.exif_transpose(im) as oriented:
            return display_image(oriented)


def metadata_root(data):
    parser = SafeET.DefusedXMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    return ET.fromstring(data, parser=parser)


def metadata_values(book):
    if not book.metadata:
        return {}
    root = metadata_root(book.metadata)
    return {c.tag: c.text or "" for c in root if isinstance(c.tag, str) and len(c) == 0}


def metadata_bytes(book, entries, updates=None, cover=None):
    if not book.metadata and not updates and cover is None:
        return None
    if book.metadata and not updates and cover is None and tuple(e.original_index for e in entries if e.image) == book.original_order:
        return book.metadata
    root = (
        metadata_root(book.metadata) if book.metadata else ET.Element("ComicInfo")
    )
    for tag, value in (updates or {}).items():
        child = root.find(tag)
        if child is None:
            child = ET.SubElement(root, tag)
        child.text = value
    images = [e for e in entries if e.image]
    count = root.find("PageCount")
    if count is None:
        count = ET.SubElement(root, "PageCount")
    count.text = str(len(images))
    pages = root.find("Pages")
    mapping = {
        e.original_index: i
        for i, e in enumerate(images)
        if e.original_index is not None
    }
    if pages is not None:
        for p in list(pages):
            if p.tag != "Page":
                continue
            try:
                old = int(p.get("Image", "-1"))
            except ValueError:
                old = -1
            if old not in mapping:
                pages.remove(p)
            else:
                p.set("Image", str(mapping[old]))
    if cover is not None:
        if pages is None:
            pages = ET.SubElement(root, "Pages")
        for p in pages:
            if p.get("Type") == "FrontCover":
                p.attrib.pop("Type")
        if cover in images:
            i = images.index(cover)
            p = next((p for p in pages if p.get("Image") == str(i)), None)
            if p is None:
                p = ET.SubElement(pages, "Page", Image=str(i))
            p.set("Type", "FrontCover")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def commit_new(temp, target):
    """Use Linux's atomic no-replace rename, with a no-clobber link fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is not None:
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temp), -100, os.fsencode(target), 1) == 0:
            return
        error = ctypes.get_errno()
        if error not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise OSError(error, os.strerror(error), str(target))
    os.link(temp, target)
    temp.unlink()


def save(
    book,
    entries,
    target,
    dpi=150,
    quality=92,
    updates=None,
    cover=None,
    cancel=None,
    progress=None,
    overwrite=False,
):
    target = Path(target)
    check(cancel)
    if not 72 <= dpi <= 600 or not 50 <= quality <= 100:
        raise ValueError("DPI must be 72–600 and JPEG quality must be 50–100.")
    fmt = target.suffix.lower()
    if fmt not in {".cbz", ".cb7", ".pdf"}:
        raise ValueError("Output must be CBZ, CB7 or PDF.")
    images = [e for e in entries if e.image]
    if not images:
        raise ValueError("A readable comic must contain at least one page.")
    if target.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".comic-writing-", suffix=fmt, dir=target.parent)
    os.close(fd)
    temp = Path(temp)
    try:
        if fmt == ".pdf":
            writer = PdfWriter()
            readers = {}
            holders = []
            try:
                for i, e in enumerate(images):
                    check(cancel)
                    if e.pdf:
                        if str(e.pdf) not in readers:
                            readers[str(e.pdf)] = PdfReader(e.pdf)
                        writer.add_page(readers[str(e.pdf)].pages[e.page])
                    else:
                        im = image_of(e)
                        w, h = im.size
                        buffer = io.BytesIO()
                        holders.append(buffer)
                        c = canvas.Canvas(buffer, pagesize=(w * 72 / dpi, h * 72 / dpi))
                        c.drawImage(
                            ImageReader(im),
                            0,
                            0,
                            width=w * 72 / dpi,
                            height=h * 72 / dpi,
                            mask="auto",
                        )
                        c.showPage()
                        c.save()
                        im.close()
                        buffer.seek(0)
                        writer.add_page(PdfReader(buffer).pages[0])
                    if progress:
                        progress(i + 1, len(images), e.name)
                values = metadata_values(book)
                values.update(updates or {})
                writer.add_metadata(
                    {
                        "/Title": values.get("Title") or target.stem,
                        "/Creator": f"Comic Utility {VERSION}",
                    }
                )
                with temp.open("wb") as f:
                    writer.write(f)
            finally:
                writer.close()
            if len(PdfReader(temp).pages) != len(images):
                raise ValueError("PDF verification failed.")
        else:
            with tempfile.TemporaryDirectory(prefix="comic-output-") as stage:
                stage = Path(stage)
                members = []
                used = set()
                page_index = 0
                for i, e in enumerate(entries):
                    check(cancel)
                    if Path(e.name).name.casefold() == "comicinfo.xml":
                        continue
                    if e.image:
                        page_index += 1
                        ext = ".jpg" if e.pdf else Path(e.name).suffix.lower()
                        name = f"pages/{page_index:05d}{ext}"
                    else:
                        name = safe_name(e.name)
                    if name.casefold() in used:
                        raise ValueError(f"Output filename collision: {name}")
                    used.add(name.casefold())
                    p = stage / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if e.pdf:
                        im = image_of(e, dpi)
                        rgb = Image.new("RGB", im.size, "white")
                        rgb.paste(
                            im,
                            mask=im.getchannel("A") if "A" in im.getbands() else None,
                        )
                        rgb.save(p, "JPEG", quality=quality)
                        im.close()
                        rgb.close()
                    else:
                        if e.image:
                            validate_image(e.path, cancel)
                        shutil.copyfile(e.path, p)
                    members.append((name, p))
                    if progress:
                        progress(i + 1, len(entries), e.name)
                xml = metadata_bytes(book, entries, updates, cover)
                if xml:
                    p = stage / "ComicInfo.xml"
                    p.write_bytes(xml)
                    members.append(("ComicInfo.xml", p))
                check(cancel)
                if fmt == ".cbz":
                    with zipfile.ZipFile(
                        temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                    ) as archive:
                        for name, p in members:
                            check(cancel)
                            archive.write(p, name)
                    with zipfile.ZipFile(temp) as archive:
                        if archive.testzip() is not None:
                            raise ValueError("ZIP checksum verification failed.")
                else:
                    with py7zr.SevenZipFile(temp, "w") as archive:
                        for name, p in members:
                            check(cancel)
                            archive.write(p, name)
                    with libarchive.file_reader(str(temp)) as archive:
                        for item in archive:
                            for block in item.get_blocks():
                                check(cancel)
        check(cancel)
        with temp.open("rb") as f:
            os.fsync(f.fileno())
        if overwrite:
            os.replace(temp, target)
        else:
            commit_new(temp, target)
        return target
    finally:
        if temp.exists():
            temp.unlink()


def extract(book, entries, selected, folder, dpi=150, quality=92, updates=None, cover=None,
            preserve_folders=True, cancel=None, progress=None):
    """Preflight the entire selection and roll back newly created files on failure."""
    root = Path(folder).resolve()
    outputs = []
    names = set()
    for e in selected:
        name = safe_name(e.name) if preserve_folders else Path(e.name).name
        out = root / name
        resolved = out.resolve()
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError(f"Unsafe extraction destination: {out}")
        if str(resolved).casefold() in names:
            raise ValueError(f"Selected filenames collide: {name}. Enable Preserve folders.")
        names.add(str(resolved).casefold())
        if out.exists() or out.is_symlink():
            raise FileExistsError(f"Existing file will not be overwritten: {out}")
        outputs.append((e, out))
    created = []
    try:
        for i, (e, out) in enumerate(outputs):
            check(cancel)
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.parent.resolve().is_relative_to(root):
                raise ValueError("Extraction folder contains a link outside the destination.")
            with out.open("xb") as f:
                created.append(out)
                if Path(e.name).name.casefold() == "comicinfo.xml":
                    f.write(metadata_bytes(book, entries, updates, cover) or b"")
                elif e.pdf:
                    with image_of(e, dpi) as im:
                        with display_image(im).convert("RGB") as rgb:
                            rgb.save(f, "JPEG", quality=quality)
                else:
                    with e.path.open("rb") as src:
                        copy_limited(src, f, MAX_ENTRY, cancel)
            if progress:
                progress(i + 1, len(outputs), f"Extracted {out.name}")
        check(cancel)
        return created
    except BaseException:
        for out in created:
            out.unlink(missing_ok=True)
        raise
