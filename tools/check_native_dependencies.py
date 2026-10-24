"""Fail packaging when a bundled ELF object has unresolved shared libraries."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
internal = root / "_internal"
env = dict(os.environ, LD_LIBRARY_PATH=str(internal))
failures = []
for soname in ("libarchive.so.13", "libEGL.so.1", "libGL.so.1", "libGLX.so.0", "libGLdispatch.so.0"):
    if not (internal / soname).is_file():
        failures.append(f"Required portable library is absent from the bundle: {soname}")
checked = 0
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue
    with path.open("rb") as f:
        if f.read(4) != b"\x7fELF":
            continue
    result = subprocess.run(["ldd", str(path)], env=env, text=True, capture_output=True)
    text = result.stdout + result.stderr
    checked += 1
    if "not found" in text or (result.returncode and "not a dynamic executable" not in text and "statically linked" not in text):
        failures.append(f"{path.relative_to(root)}:\n{text}")
if failures:
    raise SystemExit("Unresolved native dependencies:\n" + "\n".join(failures))
print(f"Native dependency check passed for {checked} ELF files")
