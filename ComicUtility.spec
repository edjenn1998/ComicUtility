"""Shared native onedir build used by build.sh and AppImage packaging."""
import ctypes.util
import json
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH)
build_root = Path(os.environ.get("COMIC_BUILD_ROOT", "/tmp/comic-utility-build"))
library = os.environ.get("LIBARCHIVE") or ctypes.util.find_library("archive")
if not library:
    raise RuntimeError("Install the system libarchive shared library before building.")
# Resolve sonames without depending on ldconfig output or pipefail/SIGPIPE behavior.
if not Path(library).is_file():
    import subprocess
    for line in subprocess.check_output(["ldconfig", "-p"], text=True).splitlines():
        if line.strip().startswith(library + " "):
            library = line.split("=>", 1)[1].strip()
            break
if not Path(library).is_file():
    raise RuntimeError(f"Cannot resolve libarchive: {library}")
pil_data, pil_binaries, pil_hidden = collect_all("PIL")
a = Analysis(
    [str(project / "launch.py")], pathex=[str(project)],
    binaries=[(library, ".")] + pil_binaries,
    datas=pil_data + [(str(project / "LICENSE"), "."),
                      (str(project / "packaging/appimage/io.github.edjenn1998.ComicUtility.svg"), ".")],
    hiddenimports=pil_hidden + ["pypdfium2_raw"],
    excludes=["tkinter"], noarchive=False,
)
build_root.mkdir(parents=True, exist_ok=True)
(build_root / "native-sources.json").write_text(json.dumps([entry[1] for entry in a.binaries], indent=2))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="comic-utility",
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="comic-utility")
