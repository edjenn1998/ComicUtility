# Comic Utility 1.1.0

A Linux desktop app for converting comics and editing their pages. Open
**CBZ/ZIP, CBR/RAR, CB7/7z, PDF, or an image folder**, then save as CBZ, CB7, or
PDF. Python, Qt, the PDF renderer, and archive codecs are included in the AppImage.
Your files stay on your computer; no account or upload is needed.

## Download and run — new to AppImages? Start here

### 1. Download the application

Open [the latest release](https://github.com/edjenn1998/ComicUtility/releases/latest)
and expand **Assets**. Download **`ComicUtility-1.1.0-x86_64.AppImage`**.
The GitHub “Source code” ZIP/tar files are for developers, not the ready-to-run app.

This download is for **64-bit Intel/AMD Linux** with a graphical desktop and
glibc 2.35 or newer (Ubuntu 22.04 and newer are the build target). It is not a
Windows, macOS, ARM/Raspberry Pi, or Alpine/musl build. See the release's
`abi-audit.json` for the exact symbol audit; that audit alone does not guarantee
operation on every Linux distribution.

### 2. Give it permission to run

An AppImage is a portable application file, not a ZIP file and not an installer.
You can keep it in Downloads or move it somewhere convenient, such as an
`Applications` folder in your home directory.

In Ubuntu's Files application:

1. Right-click the downloaded `.AppImage` and choose **Properties**.
2. Open **Permissions** and enable **Allow executing file as program**. Some file
   managers call this **Executable as Program** and put it on the main tab.
3. Close Properties, then double-click the AppImage. Choose **Run** if prompted.

You do **not** need to install Python or run the application with `sudo`.
The first launch can take a moment. An automatic application-menu entry is not
installed; you can launch the same file again whenever you want to use the app.

### Terminal alternative

Open a terminal in the folder containing the download (in Ubuntu Files,
right-click the folder background and choose **Open in Terminal**), then run:

```sh
chmod +x ./ComicUtility-1.1.0-x86_64.AppImage
./ComicUtility-1.1.0-x86_64.AppImage
```

Use the actual filename you downloaded. The leading `./` means “run the file in
this folder.” If the terminal says “No such file,” check that you opened the
terminal in the download's folder.

### If double-clicking does nothing or mounting is blocked

This release uses the modern, statically linked AppImage runtime: **you do not
need to install the older `libfuse2`/`libfuse2t64` package**, unlike many older
AppImages. Normal launching still uses the kernel's FUSE mount facility. If your
computer restricts FUSE/mounting, or you see a FUSE or permission error, use the
built-in **no-FUSE launch mode**:

```sh
./ComicUtility-1.1.0-x86_64.AppImage --appimage-extract-and-run
```

This extracts the app to a temporary folder, runs it, and cleans up after exit.
No FUSE package installation or administrator access is required. Ensure your
temporary folder has enough space. If the filesystem containing the download
does not allow executable files, move the AppImage to your home folder first.

For a reusable extracted copy:

```sh
./ComicUtility-1.1.0-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

If an error mentions a newer `GLIBC` version, your distribution is too old for
this build; installing FUSE will not fix that. If you still have trouble, run the
app from a terminal and include the error text and your Linux version in a
[GitHub issue](https://github.com/edjenn1998/ComicUtility/issues).

### Updates, removal, and optional checksum verification

Updates are manual: download the new AppImage, make it executable, and use it in
place of the older one. To remove the app, delete the AppImage (and an extracted
`squashfs-root` folder if you created one). Your comics are separate files and
remain where you saved them. Preferences are stored in
`~/.config/edjenn1998/ComicUtility.conf`.

Optional: download `SHA256SUMS` beside the release assets and verify the AppImage:

```sh
sha256sum --ignore-missing --check SHA256SUMS
```

The AppImage should report **OK**. This checks download integrity, not publisher
identity.

## Comic editor

- Open a comic, recursively import an image folder, or start a new comic.
- Select a page to preview it. **Fit page / Actual pixels** controls preview size.
  Rendering runs in the background, with small bounded thumbnails.
- Add, remove, replace, reorder pages, or make a page the front cover.
- **Show all internal files** includes XML and other non-page files. Newly created
  ComicInfo metadata appears here too and can be extracted or removed.
- **Undo / Redo** retains up to 30 edits. Returning to the saved state clears the
  unsaved-edits indicator. Opening another comic or closing asks before discarding edits.
- **Metadata** edits common ComicInfo fields; Summary supports multiple lines.
  Unknown XML elements, comments, and processing instructions are preserved when
  rewriting. Unedited metadata is retained byte-for-byte when page order is unchanged.
- **Extract** preserves folders by default, preflights collisions, and never
  overwrites existing files. Failed/cancelled extraction removes files created by
  that operation. Clear **Preserve folders when extracting** for a flat extraction.
- **Save As** chooses CBZ, CB7, or PDF. Existing destinations require confirmation.
  A successful save updates the displayed document name.
- Output folder, conversion settings, and window geometry are remembered.

Shortcuts: **Ctrl+O** open, **Ctrl+Shift+S** save, **Ctrl+Z** undo,
**Ctrl+Shift+Z / Ctrl+Y** redo. Drag a comic into the editor to open it, images to
add them, or comics into Batch conversion to queue them.

## Conversion and batch behavior

Archive images retain their original bytes unless replaced. Saved archive pages
use `pages/00001.ext`, `pages/00002.ext`, etc. to preserve reading order. Auxiliary
filenames are retained; additions are renamed when needed to avoid collisions.
Every frame of an archive image is fully decoded for validation before saving.

**PDF → CBZ/CB7:** each page is rendered to JPEG (default 150 DPI, quality 92).
Increase DPI for small text. Archive output cannot preserve selectable PDF text,
links, or interactive content.

**PDF → PDF:** selected original page objects retain text and vector content.
Added images become PDF pages at the chosen DPI. PDF output receives a title,
not full ComicInfo metadata; non-page files are omitted. Animated/multipage images
use their first frame for PDF output; archive output preserves the original file.

**Batch conversion:** add files or scan a folder, choose an output folder and
format, then click **Convert batch**. Originals are preserved. Existing outputs
and name collisions are skipped. Results show full destinations and totals for
saved, skipped, failed, and cancelled files. Use **Copy results** or **Export
results** to keep the report. Cancellation keeps completed comics and discards
the current uncommitted output. Compression, validation, and some PDF-library
calls can delay cancellation until the next safe step.

## File protection and limits

Input is staged in a private temporary workspace. Archive path traversal,
case-insensitive duplicate names, links, and special files are rejected. Limits:
**50,000 entries, 32 GiB of staged data, 2 GiB per input/staged file**, and 16 MiB
for ComicInfo XML. Editing and retained undo/redo files count toward workspace
limits; unreferenced staged files are reclaimed. PDF renders are limited to
100 million pixels per page; Pillow also applies image decompression-bomb limits.
Large comics require free temporary and destination disk space.

Outputs are staged on the destination filesystem, checked, then committed
atomically. CBZ checks ZIP checksums; CB7 is decoded after writing; PDF checks
page count. No-clobber saves use atomic no-replace rename, with a hard-link
fallback. The app does not repair damaged archives, support passwords, or join
multipart RAR sets. Some RAR variants may be unsupported. CBR is input-only.

## Source, tests, and building

Use **Python 3.12**. The pinned Qt version does not support Python 3.14.
Source operation needs system libarchive and GUI/OpenGL libraries. On Ubuntu:

```sh
sudo apt update
sudo apt install python3.12-venv libarchive13 libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python launch.py
```

Ubuntu 22.04 does not provide Python 3.12 in its default repositories; use the
AppImage for the easiest setup, or supply a compatible Python interpreter for
development. Newer Ubuntu releases may name the system archive package
`libarchive13t64` instead of `libarchive13`.

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen python launch.py --self-test
```

See [APPIMAGE.md](APPIMAGE.md) for pinned release builds and [CHANGELOG.md](CHANGELOG.md)
for changes. GitHub Actions tests and builds on Ubuntu 22.04. Generated binaries,
checksums, dependency lists, and the actual ABI audit are **release assets**.

## Licensing and historical build records

Comic Utility is **GPL-3.0**. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
Current release notices are generated from the build's installed packages,
including PDFium and native-library copyright files, and included inside the AppImage.

The pre-existing compressed source/license archives, `abi-audit.json`,
`build-environment.txt`, compatibility manifests, and `LIBARCHIVE-BUILD.md` are
historical **1.0** build records. They are retained for provenance; use the
tracked `packaging/`, current build requirements, and release assets for 1.1.0.
