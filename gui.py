from __future__ import annotations

import io
import shutil
import sys
import threading
from pathlib import Path

from engine import (
    FORMATS,
    IMAGES,
    Book,
    Cancelled,
    image_of,
    metadata_values,
    save,
)
from PIL import Image
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

STYLE = """
QWidget {background:#151d2b;color:#e7edf7;font-size:14px;} QMainWindow {background:#151d2b;}
QLabel#title {font-size:27px;font-weight:700;} QLabel#muted {color:#a4b2c7;}
QPushButton {background:#273449;border:1px solid #40516a;border-radius:6px;padding:8px 13px;}
QPushButton:hover {background:#344760;} QPushButton:disabled {color:#718096;background:#202a39;border-color:#2d394b;}
QPushButton#primary {background:#207d75;border-color:#399f93;font-weight:600;} QPushButton#primary:hover {background:#278e84;}
QLineEdit,QSpinBox,QComboBox {background:#202b3d;border:1px solid #43536c;border-radius:4px;padding:6px;}
QListWidget {background:#101722;border:1px solid #34425a;border-radius:5px;} QListWidget::item {padding:7px;border-bottom:1px solid #233047;} QListWidget::item:selected {background:#28525c;}
QTabWidget::pane {border:1px solid #34425a;border-radius:5px;} QTabBar::tab {padding:12px 24px;background:#202b3d;} QTabBar::tab:selected {background:#28525c;}
QGroupBox {border:1px solid #34425a;border-radius:5px;margin-top:12px;padding-top:10px;} QGroupBox::title {subcontrol-origin:margin;left:12px;}
QProgressBar {border:1px solid #40516a;border-radius:4px;background:#202b3d;text-align:center;} QProgressBar::chunk {background:#278e84;}

QScrollArea {border:1px solid #34425a;background:#0b111b;} QToolTip {background:#e7edf7;color:#101722;}
"""


class Task(QThread):
    result = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(
                self.fn(self.cancel, lambda a, b, c: self.progress.emit(a, b, c))
            )
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


def button(text, fn, primary=False):
    b = QPushButton(text)
    b.clicked.connect(fn)
    if primary:
        b.setObjectName("primary")
    return b


def pixmap(im):
    buffer = io.BytesIO()
    im.save(buffer, "PNG")
    p = QPixmap()
    p.loadFromData(buffer.getvalue())
    return p


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Comic Utility 1.0")
        self.resize(1240, 820)
        self.setMinimumSize(980, 700)
        self.setAcceptDrops(True)
        self.book = None
        self.entries = []
        self.updates = {}
        self.cover = None
        self.dirty = False
        self.history = []
        self.task = None
        self.previewpix = None
        self.fit = True
        self.queue = []
        self.previewcache = {}
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(12)
        self.setCentralWidget(root)
        title = QLabel("Comic Utility")
        title.setObjectName("title")
        outer.addWidget(title)
        subtitle = QLabel(
            "Convert, arrange and share your comics. Your originals stay intact until you choose to replace them."
        )
        subtitle.setObjectName("muted")
        outer.addWidget(subtitle)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.editor = QWidget()
        self.batch = QWidget()
        self.tabs.addTab(self.editor, "Comic editor")
        self.tabs.addTab(self.batch, "Batch conversion")
        self.build_editor()
        self.build_batch()
        footer = QHBoxLayout()
        self.status = QLabel("Open a comic or import a folder of images to begin.")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        footer.addWidget(self.progress)
        self.cancelbtn = button("Cancel", self.cancel)
        self.cancelbtn.setEnabled(False)
        footer.addWidget(self.cancelbtn)
        outer.addLayout(footer)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_file)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.save_as)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        self.editor.setEnabled(True)
        self.refresh()

    def build_editor(self):
        layout = QVBoxLayout(self.editor)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(button("Open comic…", self.open_file, True))
        row.addWidget(button("New comic", self.new_book))
        row.addWidget(button("Import image folder…", self.open_folder))
        row.addStretch()
        self.name = QLabel("No comic open")
        row.addWidget(self.name)
        layout.addLayout(row)
        split = QSplitter()
        layout.addWidget(split, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.allfiles = QCheckBox("Show all internal files")
        self.allfiles.toggled.connect(self.refresh)
        ll.addWidget(self.allfiles)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setIconSize(QSize(48, 64))
        self.list.currentItemChanged.connect(self.preview)
        ll.addWidget(self.list, 1)
        split.addWidget(left)
        actions = QHBoxLayout()
        actions.addWidget(button("Add…", self.add))
        actions.addWidget(button("Remove", self.remove))
        actions.addWidget(button("Replace…", self.replace))
        ll.addLayout(actions)
        actions = QHBoxLayout()
        actions.addWidget(button("Move up", lambda: self.move(-1)))
        actions.addWidget(button("Move down", lambda: self.move(1)))
        actions.addWidget(button("Make cover", self.make_cover))
        ll.addLayout(actions)
        actions = QHBoxLayout()
        actions.addWidget(button("Undo", self.undo))
        actions.addWidget(button("Extract…", self.extract))
        actions.addWidget(button("Metadata…", self.metadata))
        ll.addLayout(actions)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.pageinfo = QLabel("Page preview")
        rl.addWidget(self.pageinfo)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.image = QLabel("Open CBZ, CBR, CB7 or PDF\n\nSelect a page to preview it.")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image)
        rl.addWidget(self.scroll, 1)
        controls = QHBoxLayout()
        controls.addWidget(button("Fit page", lambda: self.zoom(True)))
        controls.addWidget(button("Actual pixels", lambda: self.zoom(False)))
        controls.addStretch()
        controls.addWidget(button("Previous", lambda: self.step(-1)))
        controls.addWidget(button("Next", lambda: self.step(1)))
        rl.addLayout(controls)
        split.addWidget(right)
        split.setSizes([400, 750])
        options = QHBoxLayout()
        options.addWidget(QLabel("Save as"))
        self.format = QComboBox()
        self.format.addItems(["CBZ", "PDF", "CB7"])
        options.addWidget(self.format)
        options.addWidget(QLabel("PDF render DPI"))
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(150)
        self.dpi.valueChanged.connect(self.preview)
        options.addWidget(self.dpi)
        options.addWidget(QLabel("PDF → archive JPEG quality"))
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.quality.setValue(92)
        options.addWidget(self.quality)
        self.quality.valueChanged.connect(self.preview)
        self.format.currentTextChanged.connect(self.preview)
        options.addStretch()
        self.savebtn = button("Save As…", self.save_as, True)
        options.addWidget(self.savebtn)
        layout.addLayout(options)
        hint = QLabel(
            "Archive images are preserved. PDF → CBZ/CB7 renders pages; PDF → PDF preserves original PDF pages. Saved archive pages use numbered filenames."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def build_batch(self):
        layout = QVBoxLayout(self.batch)
        row = QHBoxLayout()
        row.addWidget(button("Add comics…", self.batch_add))
        row.addWidget(button("Add folder…", self.batch_folder))
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        row.addWidget(self.recursive)
        row.addStretch()
        row.addWidget(button("Remove selected", self.batch_remove))
        row.addWidget(button("Clear list", self.batch_clear))
        layout.addLayout(row)
        self.batchlist = QListWidget()
        self.batchlist.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        layout.addWidget(self.batchlist, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Destination"))
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Choose a folder for converted copies")
        row.addWidget(self.destination, 1)
        row.addWidget(button("Browse…", self.choose_destination))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Output"))
        self.batchformat = QComboBox()
        self.batchformat.addItems(["CBZ", "PDF", "CB7"])
        row.addWidget(self.batchformat)
        row.addWidget(QLabel("PDF render DPI"))
        self.batchdpi = QSpinBox()
        self.batchdpi.setRange(72, 600)
        self.batchdpi.setValue(150)
        row.addWidget(self.batchdpi)
        row.addWidget(QLabel("JPEG quality"))
        self.batchquality = QSpinBox()
        self.batchquality.setRange(50, 100)
        self.batchquality.setValue(92)
        row.addWidget(self.batchquality)
        row.addStretch()
        row.addWidget(button("Convert batch", self.batch_run, True))
        layout.addLayout(row)
        hint = QLabel(
            "Existing outputs are skipped. Each result shows its full destination. Cancellation keeps completed outputs and leaves the current comic uncommitted."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def error(self, msg):
        QMessageBox.warning(self, "Comic Utility", msg)

    def run(self, fn, success, message):
        if self.task:
            return
        self.status.setText(message)
        self.tabs.setEnabled(False)
        self.cancelbtn.setEnabled(True)
        self.progress.setRange(0, 0)
        self._success = success
        task = Task(fn)
        self.task = task
        task.progress.connect(self.update_progress)
        task.result.connect(self.task_result)
        task.failed.connect(self.task_failed)
        task.finished.connect(self.task_finished)
        task.start()

    def update_progress(self, a, b, msg):
        self.status.setText(msg)
        if b:
            self.progress.setRange(0, b)
            self.progress.setValue(a)
        else:
            self.progress.setRange(0, 0)

    def task_result(self, result):
        self._success(result)

    def task_failed(self, msg):
        self.status.setText(msg)
        self.error(msg)

    def task_finished(self):
        self.tabs.setEnabled(True)
        self.cancelbtn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.task.deleteLater()
        self.task = None

    def cancel(self):
        if self.task:
            self.task.cancel.set()
            self.status.setText("Cancelling at the next safe step…")
            self.cancelbtn.setEnabled(False)

    def confirm_discard(self):
        if not self.dirty:
            return True
        return (
            QMessageBox.question(
                self,
                "Unsaved changes",
                "Discard the current unsaved edits?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def new_book(self):
        if self.task or not self.confirm_discard():
            return
        book = Book()
        book.source = Path.home() / "Untitled.cbz"
        self.loaded(book)
        self.dirty = True
        self.refresh()
        self.status.setText("New comic • add images to begin.")

    def open_file(self):
        if self.task:
            return
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Open comic",
            "",
            "Comics (*.cbz *.cbr *.cb7 *.pdf *.zip *.rar *.7z);;All files (*)",
        )
        if p:
            self.load(p)

    def open_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Import image folder")
        if p:
            self.load(p)

    def load(self, p):
        if self.task or not self.confirm_discard():
            return
        self.run(lambda c, pr: Book.load(p, c, pr), self.loaded, "Opening comic…")

    def loaded(self, book):
        if self.book:
            self.book.close()
        self.book = book
        self.entries = list(book.entries)
        self.updates = {}
        self.cover = None
        self.dirty = False
        self.history = []
        self.previewcache = {}
        self.name.setText(book.source.name)
        self.refresh()
        self.status.setText(
            f"Opened {book.source.name} • {sum(e.image for e in self.entries)} pages • {len(self.entries)} internal files"
        )

    def remember(self):
        self.history.append(
            (list(self.entries), dict(self.updates), self.cover, self.book.metadata)
        )
        self.history = self.history[-30:]
        self.dirty = True

    def refresh(self, *args):
        selected = self.current()
        self.list.blockSignals(True)
        self.list.clear()
        for e in self.entries:
            if not self.allfiles.isChecked() and not e.image:
                continue
            item = QListWidgetItem(("★ " if e is self.cover else "") + e.name)
            item.setData(Qt.ItemDataRole.UserRole, e)
            item.setToolTip(e.name)
            self.list.addItem(item)
            if id(e) in self.previewcache:
                item.setIcon(self.previewcache[id(e)])
            if e is selected:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.preview()
        self.savebtn.setEnabled(bool(self.book))
        self.name.setText(
            (self.book.source.name if self.book else "No comic open")
            + (" • unsaved edits" if self.dirty else "")
        )

    def current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def preview(self, *args):
        e = self.current()
        self.previewpix = None
        if not e:
            self.image.setText("Open a comic or add images to begin.")
            self.pageinfo.setText("Page preview")
            return
        if not e.image:
            self.image.setText(
                f"Internal file: {e.name}\n\nSelect an image for a page preview."
            )
            self.pageinfo.setText(e.name)
            return
        try:
            im = image_of(e, self.dpi.value(), self.fit)
            if e.pdf and self.format.currentText() != "PDF":
                rgb = Image.new("RGB", im.size, "white")
                rgb.paste(im, mask=im.getchannel("A") if "A" in im.getbands() else None)
                encoded = io.BytesIO()
                rgb.save(encoded, "JPEG", quality=self.quality.value())
                im.close()
                rgb.close()
                encoded.seek(0)
                with Image.open(encoded) as decoded:
                    im = decoded.copy()
            self.previewpix = pixmap(im)
            detail = (
                f" • {self.dpi.value()} DPI / JPEG {self.quality.value()}"
                if e.pdf and self.format.currentText() != "PDF"
                else ""
            )
            self.pageinfo.setText(
                f"{e.name} • preview {im.width} × {im.height}{detail}"
            )
            im.close()
            icon = QIcon(self.previewpix)
            self.previewcache[id(e)] = icon
            self.list.currentItem().setIcon(icon)
            self.show_preview()
        except Exception as exc:
            self.image.setText(f"Preview unavailable\n{exc}")
            self.pageinfo.setText(e.name)

    def show_preview(self):
        if self.previewpix:
            if self.fit:
                size = self.scroll.viewport().size() - QSize(24, 24)
                self.image.setPixmap(
                    self.previewpix.scaled(
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.image.setMinimumSize(1, 1)
            else:
                self.image.setPixmap(self.previewpix)
                self.image.setMinimumSize(self.previewpix.size())

    def zoom(self, fit):
        self.fit = fit
        self.preview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.show_preview)

    def step(self, n):
        self.list.setCurrentRow(
            max(0, min(self.list.count() - 1, self.list.currentRow() + n))
        )

    def add(self):
        if not self.book:
            self.open_folder()
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add images or internal files",
            "",
            "Images (*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tif *.tiff *.avif);;All files (*)",
        )
        if not paths:
            return
        try:
            added = self.book.add(paths)
            if any(Path(e.name).name.casefold() == "comicinfo.xml" for e in added):
                raise ValueError(
                    "Use Metadata to edit ComicInfo.xml; adding a second metadata file is not supported."
                )
            self.remember()
            current = self.current()
            at = self.entries.index(current) + 1 if current else len(self.entries)
            self.entries[at:at] = added
            self.refresh()
        except Exception as exc:
            self.error(str(exc))

    def remove(self):
        chosen = self.selected()
        if not chosen:
            return
        if not any(e.image and e not in chosen for e in self.entries):
            self.error("Keep at least one comic page.")
            return
        self.remember()
        self.entries = [e for e in self.entries if e not in chosen]
        if self.cover in chosen:
            self.cover = None
        if any(Path(e.name).name.casefold() == "comicinfo.xml" for e in chosen):
            self.book.metadata = None
            self.updates = {}
        self.refresh()

    def replace(self):
        e = self.current()
        if not e or not e.image:
            return
        p, _ = QFileDialog.getOpenFileName(
            self,
            "Replace selected page",
            "",
            "Images (*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tif *.tiff *.avif)",
        )
        if p:
            try:
                new = self.book.add([p])[0]
                new.original_index = e.original_index
                self.remember()
                self.entries[self.entries.index(e)] = new
                if self.cover is e:
                    self.cover = new
                self.refresh()
            except Exception as exc:
                self.error(str(exc))

    def move(self, direction):
        chosen = self.selected()
        if not chosen:
            return
        positions = [i for i, e in enumerate(self.entries) if e in chosen]
        if (
            direction < 0
            and positions[0] == 0
            or direction > 0
            and positions[-1] == len(self.entries) - 1
        ):
            return
        self.remember()
        for i in positions if direction < 0 else reversed(positions):
            self.entries[i], self.entries[i + direction] = (
                self.entries[i + direction],
                self.entries[i],
            )
        self.refresh()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in chosen)

    def make_cover(self):
        e = self.current()
        if e and e.image:
            self.remember()
            self.entries.remove(e)
            self.entries.insert(0, e)
            self.cover = e
            self.refresh()

    def undo(self):
        if self.task:
            return
        if self.history:
            self.entries, self.updates, self.cover, self.book.metadata = (
                self.history.pop()
            )
            self.dirty = True
            self.refresh()

    def metadata(self):
        if not self.book:
            return
        try:
            values = metadata_values(self.book)
            values.update(self.updates)
        except Exception as exc:
            self.error(f"Cannot parse ComicInfo.xml: {exc}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Comic metadata")
        dialog.resize(520, 600)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        fields = {}
        for name in [
            "Title",
            "Series",
            "Number",
            "Volume",
            "Writer",
            "Penciller",
            "Inker",
            "Colorist",
            "Letterer",
            "CoverArtist",
            "Publisher",
            "Year",
            "Month",
            "Genre",
            "Summary",
        ]:
            entry = QLineEdit(values.get(name, ""))
            fields[name] = entry
            form.addRow(name, entry)
        layout.addLayout(form)
        note = QLabel(
            "Other existing XML fields are preserved. PDF output receives a title; ComicInfo.xml is stored in CBZ/CB7."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec():
            self.remember()
            self.updates = {n: w.text() for n, w in fields.items()}
            self.refresh()

    def extract(self):
        selected = self.selected()
        if not selected:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Extract selected files into folder"
        )
        if not folder:
            return
        dpi = self.dpi.value()

        def job(cancel, progress):
            from engine import check

            outputs = []
            for i, e in enumerate(selected):
                check(cancel)
                out = Path(folder) / Path(e.name).name
                if out.exists():
                    raise FileExistsError(
                        f"Existing file will not be overwritten: {out}"
                    )
                # Exclusive creation prevents race-time overwrites.
                with out.open("xb") as f:
                    try:
                        if e.pdf:
                            im = image_of(e, dpi)
                            im.convert("RGB").save(f, "JPEG", quality=92)
                            im.close()
                        else:
                            with e.path.open("rb") as src:
                                shutil.copyfileobj(src, f)
                    except BaseException:
                        f.close()
                        out.unlink(missing_ok=True)
                        raise
                outputs.append(out)
                progress(i + 1, len(selected), f"Extracted {out.name}")
            return outputs

        self.run(
            job,
            lambda out: self.status.setText(f"Extracted {len(out)} files to {folder}"),
            "Extracting files…",
        )

    def save_as(self):
        if not self.book or self.task:
            return
        fmt = self.format.currentText().lower()
        suggested = self.book.source.with_name(self.book.source.stem + "-edited." + fmt)
        p, _ = QFileDialog.getSaveFileName(
            self,
            "Save comic as",
            str(suggested),
            f"{fmt.upper()} (*.{fmt})",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not p:
            return
        if Path(p).suffix.lower() not in {".cbz", ".cb7", ".pdf"}:
            p += "." + fmt
        overwrite = Path(p).exists()
        if (
            overwrite
            and QMessageBox.question(
                self,
                "Replace existing file?",
                f"Replace {p}?\nThe new file is checked before replacement.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        book = self.book
        entries = list(self.entries)
        updates = dict(self.updates)
        cover = self.cover
        dpi = self.dpi.value()
        quality = self.quality.value()
        self.run(
            lambda c, pr: save(
                book, entries, p, dpi, quality, updates, cover, c, pr, overwrite
            ),
            self.saved,
            "Saving and verifying comic…",
        )

    def saved(self, p):
        self.dirty = False
        self.history = []
        self.refresh()
        self.status.setText(f"Saved and verified: {p}")

    def batch_add(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add comics", "", "Comics (*.cbz *.cbr *.cb7 *.pdf *.zip *.rar *.7z)"
        )
        self.enqueue(paths)

    def batch_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Find comics in folder")
        if folder:
            paths = (
                Path(folder).rglob("*")
                if self.recursive.isChecked()
                else Path(folder).glob("*")
            )
            self.enqueue(
                [str(p) for p in paths if p.is_file() and p.suffix.lower() in FORMATS]
            )

    def enqueue(self, paths):
        for p in paths:
            p = str(Path(p).resolve())
            if p not in self.queue:
                self.queue.append(p)
                self.batchlist.addItem(p)

    def batch_remove(self):
        for row in sorted(
            [self.batchlist.row(i) for i in self.batchlist.selectedItems()],
            reverse=True,
        ):
            self.queue.pop(row)
            self.batchlist.takeItem(row)

    def batch_clear(self):
        self.queue = []
        self.batchlist.clear()

    def choose_destination(self):
        p = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if p:
            self.destination.setText(p)

    def batch_run(self):
        if not self.queue:
            self.error("Add comics first.")
            return
        dest = self.destination.text().strip()
        if not dest:
            self.error("Choose an output folder first.")
            return
        paths = list(self.queue)
        fmt = self.batchformat.currentText().lower()
        dpi = self.batchdpi.value()
        quality = self.batchquality.value()
        destination = Path(dest)

        def job(cancel, progress):
            results = []
            for i, path in enumerate(paths):
                if cancel.is_set():
                    results.append((i, "Cancelled before starting"))
                    break
                out = destination / (Path(path).stem + "." + fmt)
                book = None
                if out.exists():
                    results.append((i, f"Skipped: output exists — {out}"))
                    continue
                try:
                    book = Book.load(
                        path,
                        cancel,
                        lambda a, b, m: progress(
                            a,
                            b,
                            f"{i + 1}/{len(paths)} • Opening {Path(path).name} • {m}",
                        ),
                    )
                    save(
                        book,
                        book.entries,
                        out,
                        dpi,
                        quality,
                        cancel=cancel,
                        progress=lambda a, b, m: progress(
                            a, b, f"{i + 1}/{len(paths)} • {m}"
                        ),
                    )
                    results.append((i, f"Saved: {out}"))
                except Exception as exc:
                    results.append(
                        (
                            i,
                            f"{'Cancelled' if isinstance(exc, Cancelled) else 'Failed'}: {exc}",
                        )
                    )
                    if isinstance(exc, Cancelled):
                        break
                finally:
                    if book:
                        book.close()
            return results

        def done(results):
            for i, message in results:
                self.batchlist.item(i).setText(f"{paths[i]}\n{message}")
            self.status.setText(
                f"Batch finished • {sum(m.startswith('Saved') for _, m in results)} saved • see results above."
            )

        self.run(job, done, "Starting batch conversion…")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.task:
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self.tabs.currentIndex() == 1:
            self.enqueue([p for p in paths if Path(p).suffix.lower() in FORMATS])
        elif paths and all(Path(p).suffix.lower() in IMAGES for p in paths):
            if not self.book:
                self.new_book()
            if self.book:
                try:
                    added = self.book.add(paths)
                    self.remember()
                    self.entries.extend(added)
                    self.refresh()
                except Exception as exc:
                    self.error(str(exc))
        elif paths:
            self.load(paths[0])

    def closeEvent(self, event):
        if self.task:
            self.error(
                "Cancel the current operation and wait for it to finish before closing."
            )
            event.ignore()
            return
        if not self.confirm_discard():
            event.ignore()
            return
        if self.book:
            self.book.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        QTimer.singleShot(0, lambda: window.load(sys.argv[1]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
