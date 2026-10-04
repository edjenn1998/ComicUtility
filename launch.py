import sys
from pathlib import Path

if "--self-test" in sys.argv:
    import tempfile

    from engine import Book, image_of, save
    from gui import STYLE, Window
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source = root / "pages"
        source.mkdir()
        for i, color in enumerate(["red", "blue", "green"]):
            Image.new("RGB", (240, 360), color).save(source / f"{i + 1}.png")
        book = Book.load(source)
        for fmt in ["cbz", "cb7", "pdf"]:
            out = root / f"comic.{fmt}"
            save(book, book.entries, out)
            check = Book.load(out)
            assert sum(e.image for e in check.entries) == 3
            if fmt == "pdf":
                im = image_of(check.entries[0], 72)
                assert im.width > 0
                im.close()
                save(check, check.entries, root / "from-pdf.cbz", dpi=72)
            check.close()
        window = Window()
        window.show()
        window.loaded(book)
        app.processEvents()
        assert window.list.count() == 3
        window.list.setCurrentRow(1)
        window.make_cover()
        assert window.cover is window.entries[0]
        window.undo()
        assert window.cover is None
        window.dirty = False
        if "--screenshot" in sys.argv:
            index = sys.argv.index("--screenshot")
            window.grab().save(sys.argv[index + 1])
        window.close()
        app.processEvents()
    if "--rar-fixture" in sys.argv:
        import libarchive

        fixture = sys.argv[sys.argv.index("--rar-fixture") + 1]
        with libarchive.file_reader(fixture) as archive:
            assert (
                sum(len(block) for entry in archive for block in entry.get_blocks()) > 0
            )
    print("Comic Utility self-test passed: CBZ, CB7, PDF rendering and GUI editing")
    raise SystemExit(0)
from gui import main

raise SystemExit(main())
