"""Shared native onedir build used by build.sh and AppImage packaging."""
import ctypes.util
import json
import os
import subprocess
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH)
build_root = Path(os.environ.get("COMIC_BUILD_ROOT", "/tmp/comic-utility-build"))
cache = subprocess.check_output(["ldconfig", "-p"], text=True).splitlines()


def resolve_library(name):
    library = ctypes.util.find_library(name)
    if name == "archive":
        library = os.environ.get("LIBARCHIVE") or library
    if library and Path(library).is_file():
        return library
    for line in cache:
        if library and line.strip().startswith(library + " "):
            return line.split("=>", 1)[1].strip()
    raise RuntimeError(f"Install the system {name} shared library before building.")


# PyInstaller intentionally leaves these GLVND dispatch libraries to the host
# unless explicitly requested. Bundle the vendor-neutral shims, not GPU drivers,
# so Qt can start on minimal desktops too; GPU-specific implementations stay native.
native = [resolve_library(name) for name in ("archive", "EGL", "GL", "GLX", "GLdispatch")]
pil_data, pil_binaries, pil_hidden = collect_all("PIL")
a = Analysis(
    [str(project / "launch.py")], pathex=[str(project)],
    binaries=[(library, ".") for library in native] + pil_binaries,
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
