# Comic Utility 1.0

A Python desktop utility for comic conversion and page editing. Open CBZ/ZIP,
CBR/RAR, CB7/7z, PDF or an image folder. Save CBZ (default), CB7 or PDF.
CBR is input-only. The packaged executable includes Python, Qt, archive codecs
and the PDF renderer; no Python, RAR or 7-Zip installation is needed.

## Run

Make `ComicUtility-1.0-Linux-x86_64` executable in your file manager's Properties
and double-click it. Alternatively:

    chmod +x ComicUtility-1.0-Linux-x86_64
    ./ComicUtility-1.0-Linux-x86_64

A first launch takes a moment while the single-file application unpacks its
libraries into a temporary directory. A graphical Linux desktop is required.
The x86-64 executable is for Intel/AMD GNU/Linux, not ARM, Windows, macOS or
musl-based Alpine. Its audited minimum glibc is 2.34 (see `abi-audit.json`). The
packaged GUI was tested on the build environment; symbol compatibility is not
a promise of operation on every distribution. Separate native builds are
required for other architectures.

## Comic editor

- Open a comic, import an image folder (including subfolders), or start a new comic.
- Select a page for a preview. Fit page / Actual pixels control preview size.
  Thumbnails appear as pages are viewed. Previous / Next browse the file list.
- Add images or other internal files, remove selected files, replace a page,
  move selected pages up/down, or make the selected page the front cover.
- Show all internal files to access XML and other non-page files.
- Undo restores the last edit (up to 30 operations). Unsaved changes trigger a
  discard confirmation when opening another comic or closing.
- Metadata edits common ComicInfo.xml fields and preserves other XML fields.
  Cover and page-index metadata are adjusted for removed/reordered pages.
- Extract saves selected files without overwriting existing files.
- Save As chooses CBZ, CB7 or PDF. An existing destination requires confirmation.
  Saving an edited CBR creates a new supported format.

Keyboard shortcuts: Ctrl+O opens, Ctrl+Shift+S saves, Ctrl+Z undoes.
Drag comic files into the editor to open, images to add, or comics into Batch
conversion to queue them.

## Conversion behavior

Archive images retain their original bytes unless replaced. Output archive pages
use `pages/00001.ext`, `pages/00002.ext`, etc. to preserve the chosen reading
order across readers; other internal filenames are retained. Filename collisions
are rejected. ComicInfo.xml is rewritten only to apply metadata/page changes.

PDF to CBZ/CB7 renders each selected PDF page into a JPEG. Default: 150 DPI,
JPEG quality 92. Increase DPI for small text or lower it to reduce file size.
Selecting a PDF page previews the DPI and JPEG quality settings (fit preview may
be reduced); Actual pixels shows the full render at the chosen DPI and quality. Archive output
cannot retain selectable PDF text, links or interactive content.

PDF to PDF retains original selected PDF page objects, including text and vector
content. Newly added images become separate PDF pages at the chosen DPI. PDF
output stores a title, not the full ComicInfo.xml metadata. Non-page auxiliary
archive files are omitted from PDF output. Animated/multipage image files use
their first frame/page for PDF output, while archive output preserves the entire
original image file.

Batch conversion accepts files or scans a folder. Outputs go to a selected
folder. Originals are preserved; existing outputs (including name collisions)
are skipped with a visible explanation. Each result lists its full destination.
Cancellation retains completed comics and discards the current uncommitted
output. Compression and checksum validation may delay cancellation until a safe
step. Re-running a batch will skip its already completed outputs.

## File protection and limitations

Archives are staged in a private temporary workspace, with path traversal,
links, duplicate names and special-file entries rejected. Workspaces allow up to
50,000 input entries, 32 GiB decompressed total and 2 GiB per file. PDF renders
are limited to 100 million pixels per page. Large comics need enough temporary
and destination disk space. The whole application runs without administrator
privileges. Files are not uploaded anywhere.

Output is written to a temporary file on the destination filesystem, checked,
and committed atomically. CBZ checks all ZIP checksums and validates image files;
CB7 is fully decoded after writing; PDF verifies its page count. No-clobber saves use Linux's atomic no-replace rename, with a hard-link fallback.
A filesystem without either operation may reject the save rather than weakening
the protection against overwriting an existing file.
This utility does not repair damaged RAR data, support password-protected files,
or join multipart RAR sets. Some proprietary RAR variants can be unsupported.

## Source and tests

Python 3.12 is recommended. Source operation requires a system libarchive
shared library (e.g. `libarchive13` on Debian/Ubuntu; `libarchive` on Arch):

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
    python launch.py
    QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
    QT_QPA_PLATFORM=offscreen python launch.py --self-test

`build-environment.txt` records exact package versions from the release build.
`ComicUtility.spec` uses `COMIC_COMPAT_ROOT` pointing to extracted compatibility
libraries, including the rebuilt patched libarchive. Run PyInstaller from any
directory; build intermediates should be on a local filesystem under `/tmp`:

    COMIC_COMPAT_ROOT=/path/to/root LD_LIBRARY_PATH=/path/to/root/usr/lib/x86_64-linux-gnu:/path/to/root/lib/x86_64-linux-gnu python -m PyInstaller --clean --noconfirm --workpath /tmp/comic-build --distpath /tmp/comic-dist ComicUtility.spec

Set `COMIC_BUILD_MODE=onedir` for an inspectable build. For a native build without
the compatibility root, use `build.sh`; its ABI depends on the build computer.

Third-party license notices are in `licenses.tar.xz'. 
