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

FORMATS = {".cbz", ".zip", ".cbr", ".rar", ".cb7", ".7z", ".pdf"}
IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}
MAX_BYTES = 32 * 1024**3
MAX_ENTRY = 2 * 1024**3
MAX_FILES = 50000
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

    def close(self):
        self.temp.cleanup()

    def stage(self, name, data=None, source=None):
        target = self.root / uuid.uuid4().hex
        if source:
            shutil.copyfile(source, target)
        else:
            target.write_bytes(data)
        return Entry(safe_name(name), target)

    @classmethod
    def load(cls, source, cancel=None, progress=None):
        self = cls()
        self.source = Path(source)
        try:
            if self.source.is_dir():
                files = sorted(
                    (
                        p
                        for p in self.source.rglob("*")
                        if p.is_file() and not p.is_symlink()
                    ),
                    key=lambda p: natural(str(p.relative_to(self.source))),
                )
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
                        self.stage(str(p.relative_to(self.source)), source=p)
                    )
                    if progress:
                        progress(i + 1, len(files), p.name)
            elif self.source.suffix.lower() == ".pdf":
                staged_pdf = self.root / "source.pdf"
                shutil.copyfile(self.source, staged_pdf)
                reader = PdfReader(staged_pdf)
                if reader.is_encrypted:
                    raise ValueError(
                        "Password-protected PDFs are not supported. Open an unlocked copy."
                    )
                if len(reader.pages) > MAX_FILES:
                    raise ValueError("Too many PDF pages.")
                self.entries = [
                    Entry(f"{i + 1:05d}.jpg", pdf=staged_pdf, page=i, original_index=i)
                    for i in range(len(reader.pages))
                ]
            else:
                total = 0
                seen = set()
                with libarchive.file_reader(str(self.source)) as archive:
                    for item in archive:
                        check(cancel)
                        if item.isdir:
                            continue
                        if not item.isfile:
                            raise ValueError(
                                "Archive contains a link or special file; only regular files are supported."
                            )
                        name = safe_name(item.pathname)
                        if name in seen:
                            raise ValueError(f"Duplicate archive entry: {name}")
                        seen.add(name)
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
                    self.metadata = e.path.read_bytes()
            if not any(e.image for e in self.entries):
                raise ValueError("No supported comic pages found.")
            return self
        except BaseException:
            self.close()
            raise

    def add(self, paths):
        existing = {e.name.casefold() for e in self.entries}
        result = []
        for path in paths:
            p = Path(path)
            name = p.name
            if p.stat().st_size > MAX_ENTRY:
                raise ValueError("Added file exceeds 2 GiB limit.")
            if p.suffix.lower() in IMAGES:
                with Image.open(p) as im:
                    im.verify()
            if name.casefold() in existing:
                n = 2
                while name.casefold() in existing:
                    name = f"{p.stem}_{n}{p.suffix}"
                    n += 1
            existing.add(name.casefold())
            result.append(self.stage(name, source=p))
        return result


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
        return ImageOps.exif_transpose(im).copy()


def metadata_values(book):
    if not book.metadata:
        return {}
    root = SafeET.fromstring(book.metadata)
    return {c.tag: c.text or "" for c in root if len(c) == 0}


def metadata_bytes(book, entries, updates=None, cover=None):
    if not book.metadata and not updates and cover is None:
        return None
    root = (
        SafeET.fromstring(book.metadata) if book.metadata else ET.Element("ComicInfo")
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
                values = updates or metadata_values(book)
                writer.add_metadata(
                    {
                        "/Title": values.get("Title") or target.stem,
                        "/Creator": "Comic Utility 1.0",
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
                            with Image.open(e.path) as image:
                                image.verify()
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
