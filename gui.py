from __future__ import annotations

import io
import sys
import threading
from collections import OrderedDict
from pathlib import Path

from engine import (
    FORMATS,
    IMAGES,
    Book,
    Cancelled,
    Entry,
    check,
    display_image,
    extract,
    image_of,
    metadata_values,
    save,
)
from PIL import Image
from PySide6.QtCore import QItemSelectionModel, QSettings, QSize, Qt, QThread, QTimer, Signal
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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from version import VERSION

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
    with display_image(im) as normalized:
        normalized.save(buffer, "PNG")
    p = QPixmap()
    p.loadFromData(buffer.getvalue())
    return p


class PreviewTask(QThread):
    ready = Signal(object)
    failed = Signal(object)

    def __init__(self, key, entry, dpi, quality, output, fit):
        super().__init__()
        self.key, self.entry = key, entry
        self.dpi, self.quality, self.output, self.fit = dpi, quality, output, fit
        self.cancel = threading.Event()

    def run(self):
        try:
            check(self.cancel)
            with image_of(self.entry, self.dpi, self.fit) as original:
                im = display_image(original)
            try:
                check(self.cancel)
                if self.entry.pdf and self.output != "PDF":
                    encoded = io.BytesIO()
                    with im.convert("RGB") as rgb:
                        rgb.save(encoded, "JPEG", quality=self.quality)
                    im.close()
                    encoded.seek(0)
                    with Image.open(encoded) as decoded:
                        im = decoded.copy()
                size = im.size
                data = io.BytesIO()
                im.save(data, "PNG")
                im.thumbnail((48, 64))
                thumb = io.BytesIO()
                im.save(thumb, "PNG")
                check(self.cancel)
                self.ready.emit((self.key, data.getvalue(), thumb.getvalue(), size))
            finally:
                im.close()
        except Cancelled:
            pass
        except Exception as exc:
            self.failed.emit((self.key, str(exc)))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Comic Utility {VERSION}")
        icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "io.github.edjenn1998.ComicUtility.svg"
        if not icon_path.exists():
            icon_path = Path(__file__).parent / "packaging/appimage/io.github.edjenn1998.ComicUtility.svg"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1240, 820)
        self.setMinimumSize(980, 700)
        self.setAcceptDrops(True)
        self.book = None
        self.entries = []
        self.updates = {}
        self.cover = None
        self.dirty = False
        self.history = []
        self.future = []
        self.saved_state = None
        self.task = None
        self.previewpix = None
        self.fit = True
        self.queue = []
        self.previewcache = OrderedDict()
        self.preview_task = None
        self.preview_request = None
        self.preview_generation = 0
        self.batch_results = []
        self.settings = QSettings("edjenn1998", "ComicUtility")
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
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo)
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.destination.setText(self.settings.value("destination", ""))
        for name in ("dpi", "quality", "batchdpi", "batchquality"):
            widget = getattr(self, name)
            widget.setValue(int(self.settings.value(name, widget.value())))
        for name in ("format", "batchformat"):
            widget = getattr(self, name)
            widget.setCurrentText(self.settings.value(name, widget.currentText()))
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
        self.removebtn = button("Remove", self.remove)
        self.replacebtn = button("Replace…", self.replace)
        actions.addWidget(self.removebtn)
        actions.addWidget(self.replacebtn)
        ll.addLayout(actions)
        actions = QHBoxLayout()
        actions.addWidget(button("Move up", lambda: self.move(-1)))
        actions.addWidget(button("Move down", lambda: self.move(1)))
        self.coverbtn = button("Make cover", self.make_cover)
        actions.addWidget(self.coverbtn)
        ll.addLayout(actions)
        actions = QHBoxLayout()
        self.undobtn = button("Undo", self.undo)
        self.redobtn = button("Redo", self.redo)
        self.extractbtn = button("Extract…", self.extract)
        actions.addWidget(self.undobtn)
        actions.addWidget(self.redobtn)
        actions.addWidget(self.extractbtn)
        actions.addWidget(button("Metadata…", self.metadata))
        ll.addLayout(actions)
        self.preserve_folders = QCheckBox("Preserve folders when extracting")
        self.preserve_folders.setChecked(True)
        ll.addWidget(self.preserve_folders)
        self.list.itemSelectionChanged.connect(self.update_actions)
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
        dpi_label = QLabel("DPI")
        dpi_label.setToolTip("PDF render resolution / physical size of image pages in PDF output")
        options.addWidget(dpi_label)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(150)
        self.dpi.valueChanged.connect(self.preview)
        options.addWidget(self.dpi)
        quality_label = QLabel("JPEG quality")
        quality_label.setToolTip("JPEG quality for PDF pages rendered to CBZ/CB7")
        options.addWidget(quality_label)
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
        results = QHBoxLayout()
        results.addWidget(button("Copy results", self.copy_results))
        results.addWidget(button("Export results…", self.export_results))
        results.addStretch()
        layout.addLayout(results)
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
        self.stop_preview()
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
        try:
            self._success(result)
        except Exception as exc:
            self.error(str(exc))

    def task_failed(self, msg):
        self.status.setText(msg)
        if not (self.task and self.task.cancel.is_set()):
            self.error(msg)

    def task_finished(self):
        self.tabs.setEnabled(True)
        self.cancelbtn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.task.deleteLater()
        self.task = None
        self.update_actions()
        self.preview()

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
        self.saved_state = None
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
        self.stop_preview()
        if self.book:
            self.book.close()
        self.book = book
        self.entries = list(book.entries)
        self.updates = {}
        self.cover = None
        self.dirty = False
        self.history = []
        self.future = []
        self.previewcache.clear()
        self.preview_generation += 1
        self.saved_state = self.snapshot()
        self.name.setText(book.source.name)
        self.refresh()
        self.status.setText(
            f"Opened {book.source.name} • {sum(e.image for e in self.entries)} pages • {len(self.entries)} internal files"
        )

    def remember(self):
        self.history.append(self.snapshot())
        self.history = self.history[-30:]
        self.future = []
        self.dirty = True

    @property
    def entries(self):
        return self.book.entries if self.book else self._empty_entries

    @entries.setter
    def entries(self, value):
        if self.book:
            self.book.entries = value
        else:
            self._empty_entries = value

    def snapshot(self):
        return (list(self.entries), dict(self.updates), self.cover,
                self.book.metadata if self.book else None)

    def update_actions(self):
        current = self.current()
        chosen = bool(self.selected())
        self.removebtn.setEnabled(chosen)
        self.extractbtn.setEnabled(chosen)
        self.replacebtn.setEnabled(bool(current and current.image))
        self.coverbtn.setEnabled(bool(current and current.image))
        self.undobtn.setEnabled(bool(self.history))
        self.redobtn.setEnabled(bool(self.future))

    def refresh(self, *args):
        selected = self.current()
        selection = {id(e) for e in self.selected()}
        if self.book:
            self.dirty = self.snapshot() != self.saved_state
            self.prune_workspace()
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
                self.list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
            item.setSelected(id(e) in selection)
        self.list.blockSignals(False)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.preview()
        self.savebtn.setEnabled(bool(self.book))
        self.update_actions()
        self.name.setText(
            (self.book.source.name if self.book else "No comic open")
            + (" • unsaved edits" if self.dirty else "")
        )

    def current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected(self):
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def stop_preview(self):
        self.preview_request = None
        if self.preview_task:
            task = self.preview_task
            task.cancel.set()
            task.wait()
            task.ready.disconnect()
            task.failed.disconnect()
            task.finished.disconnect()
            task.deleteLater()
            self.preview_task = None

    def preview(self, *args):
        e = self.current()
        self.update_actions()
        self.previewpix = None
        self.image.setMinimumSize(1, 1)
        self.preview_request = None
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
        if self.task:
            return
        key = (self.preview_generation, id(e), self.dpi.value(), self.quality.value(),
               self.format.currentText(), self.fit)
        self.preview_request = (key, e)
        self.image.setText("Loading preview…")
        self.pageinfo.setText(e.name)
        if self.preview_task:
            self.preview_task.cancel.set()
        else:
            self.start_preview()

    def start_preview(self):
        if not self.preview_request:
            return
        key, e = self.preview_request
        task = PreviewTask(key, e, key[2], key[3], key[4], key[5])
        self.preview_task = task
        task.ready.connect(self.preview_ready)
        task.failed.connect(self.preview_failed)
        task.finished.connect(self.preview_finished)
        task.start()

    def preview_ready(self, result):
        key, data, thumb, size = result
        if self.sender() is not self.preview_task or not self.preview_request or key != self.preview_request[0]:
            return
        self.previewpix = QPixmap()
        self.previewpix.loadFromData(data)
        small = QPixmap()
        small.loadFromData(thumb)
        icon = QIcon(small)
        self.previewcache[key[1]] = icon
        self.previewcache.move_to_end(key[1])
        while len(self.previewcache) > 256:
            old, _ = self.previewcache.popitem(last=False)
            for i in range(self.list.count()):
                item = self.list.item(i)
                if id(item.data(Qt.ItemDataRole.UserRole)) == old:
                    item.setIcon(QIcon())
                    break
        self.list.currentItem().setIcon(icon)
        e = self.current()
        detail = f" • {key[2]} DPI / JPEG {key[3]}" if e.pdf and key[4] != "PDF" else ""
        self.pageinfo.setText(f"{e.name} • preview {size[0]} × {size[1]}{detail}")
        self.show_preview()

    def preview_failed(self, result):
        key, message = result
        if self.sender() is self.preview_task and self.preview_request and key == self.preview_request[0]:
            self.image.setText(f"Preview unavailable\n{message}")

    def preview_finished(self):
        task = self.preview_task
        if self.sender() is not task or task is None:
            return
        self.preview_task = None
        task.deleteLater()
        if self.preview_request and (task.cancel.is_set() or task.key != self.preview_request[0]):
            self.start_preview()

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
        self.add_paths(paths)

    def add_paths(self, paths, replace=None):
        if self.task:
            return
        self.stop_preview()
        self.prune_workspace()
        current = self.current()

        def done(added):
            self.remember()
            if replace:
                new = added[0]
                new.original_index = replace.original_index
                self.entries[self.entries.index(replace)] = new
                if self.cover is replace:
                    self.cover = new
            else:
                at = self.entries.index(current) + 1 if current else len(self.entries)
                self.entries[at:at] = added
            self.prune_workspace()
            self.refresh()

        self.run(lambda c, pr: self.book.add(paths, c, pr), done, "Adding and validating files…")

    def prune_workspace(self):
        retained = list(self.entries)
        for state in self.history + self.future:
            retained.extend(state[0])
        self.book.prune(retained)
        keep = {id(e) for e in retained}
        for key in list(self.previewcache):
            if key not in keep:
                self.previewcache.pop(key)

    def remove(self):
        chosen = self.selected()
        if not chosen:
            return
        if not any(e.image and e not in chosen for e in self.entries):
            self.error("Keep at least one comic page.")
            return
        self.remember()
        self.stop_preview()
        self.entries = [e for e in self.entries if e not in chosen]
        if self.cover in chosen:
            self.cover = None
        if any(Path(e.name).name.casefold() == "comicinfo.xml" for e in chosen):
            self.book.metadata = None
            self.updates = {}
            self.cover = None
        self.prune_workspace()
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
            self.add_paths([p], replace=e)

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
            if not any(Path(item.name).name.casefold() == "comicinfo.xml" for item in self.entries):
                self.entries.append(Entry("ComicInfo.xml"))
            self.refresh()

    def undo(self):
        if self.task:
            return
        if self.history:
            self.stop_preview()
            self.future.append(self.snapshot())
            self.entries, self.updates, self.cover, self.book.metadata = (
                self.history.pop()
            )
            self.dirty = True
            self.refresh()

    def redo(self):
        if self.task or not self.future:
            return
        self.stop_preview()
        self.history.append(self.snapshot())
        self.entries, self.updates, self.cover, self.book.metadata = self.future.pop()
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
            entry = QPlainTextEdit(values.get(name, "")) if name == "Summary" else QLineEdit(values.get(name, ""))
            if name == "Summary":
                entry.setMaximumHeight(100)
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
            updates = {n: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text())
                       for n, w in fields.items()}
            updates = {n: text for n, text in updates.items() if text != metadata_values(self.book).get(n, "")}
            if updates == self.updates:
                return
            self.remember()
            self.updates = updates
            if not any(Path(e.name).name.casefold() == "comicinfo.xml" for e in self.entries):
                self.entries.append(Entry("ComicInfo.xml"))
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
        quality = self.quality.value()
        preserve = self.preserve_folders.isChecked()
        entries, updates, cover = list(self.entries), dict(self.updates), self.cover

        def job(cancel, progress):
            return extract(self.book, entries, selected, folder, dpi, quality, updates,
                           cover, preserve, cancel, progress)

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
        if self.settings.value("save_folder"):
            suggested = Path(self.settings.value("save_folder")) / suggested.name
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
        self.book.source = Path(p)
        self.saved_state = self.snapshot()
        self.dirty = False
        self.settings.setValue("save_folder", str(Path(p).parent))
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
        self.batch_results = []
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
        self.batch_results = []
        self.batchlist.clear()

    def results_text(self):
        return "\n\n".join(f"{path}\n{message}" for path, message in self.batch_results)

    def copy_results(self):
        QApplication.clipboard().setText(self.results_text())
        self.status.setText("Batch results copied to the clipboard.")

    def export_results(self):
        if not self.batch_results:
            self.error("Run a batch first to create results.")
            return
        p, _ = QFileDialog.getSaveFileName(self, "Export batch results", "comic-results.txt", "Text (*.txt)")
        if p:
            try:
                Path(p).write_text(self.results_text() + "\n", encoding="utf-8")
                self.status.setText(f"Results exported to {p}")
            except OSError as exc:
                self.error(str(exc))

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
                    results.extend((j, "Cancelled before starting") for j in range(i, len(paths)))
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
                        results.extend((j, "Cancelled before starting") for j in range(i + 1, len(paths)))
                        break
                finally:
                    if book:
                        book.close()
            return results

        def done(results):
            self.batch_results = [(paths[i], message) for i, message in results]
            for i, message in results:
                self.batchlist.item(i).setText(f"{paths[i]}\n{message}")
            counts = [f"{sum(m.startswith(label) for _, m in results)} {label.lower()}"
                      for label in ("Saved", "Skipped", "Failed", "Cancelled")]
            self.status.setText("Batch finished • " + " • ".join(counts))

        self.run(job, done, "Starting batch conversion…")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.task:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.task:
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if self.tabs.currentIndex() == 1:
            self.enqueue([p for p in paths if Path(p).suffix.lower() in FORMATS])
        elif paths and all(Path(p).suffix.lower() in IMAGES for p in paths):
            if not self.book:
                self.new_book()
            if self.book:
                self.add_paths(paths)
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
        self.stop_preview()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("destination", self.destination.text())
        for name in ("dpi", "quality", "batchdpi", "batchquality"):
            self.settings.setValue(name, getattr(self, name).value())
        for name in ("format", "batchformat"):
            self.settings.setValue(name, getattr(self, name).currentText())
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
