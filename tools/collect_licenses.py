"""Assemble notices from the actual Python environment and bundled native libraries."""
import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def collect(destination, manifest):
    project = Path(__file__).resolve().parents[1]
    destination.mkdir(parents=True, exist_ok=True)
    licenses = destination / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copyfile(project / "LICENSE", destination / "LICENSE")
    shutil.copyfile(project / "NOTICE.md", destination / "NOTICE.md")
    records = []
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = f"{dist.metadata['Name']}-{dist.version}"
        records.append(f"{dist.metadata['Name']}=={dist.version}")
        for member in dist.files or []:
            parts = [part.casefold() for part in member.parts]
            if ".." in member.parts:
                continue
            if not any(part.startswith(("license", "copying", "notice")) for part in parts):
                continue
            source = Path(dist.locate_file(member))
            if source.is_file():
                out = licenses / "python-packages" / name / member
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, out)
    (destination / "python-dependencies.txt").write_text("\n".join(records) + "\n")
    (destination / "python-runtime.txt").write_text(sys.version + "\n")

    # Reuse only version-independent license texts, never the stale 1.0 notices.
    with tarfile.open(project / "licenses.tar.xz") as archive:
        for name in ("Qt-GPL-3.txt", "Qt-LGPL-3.txt", "Python-COPYRIGHT.txt", "libarchive-COPYING"):
            data = archive.extractfile("licenses/" + name).read()
            (licenses / name).write_bytes(data)
    qt = importlib.metadata.version("PySide6_Essentials")
    (licenses / "Qt-NOTICE.txt").write_text(
        f"Qt/PySide6 {qt}, The Qt Company and contributors.\n"
        "Open-source LGPLv3/GPLv3 distribution; Comic Utility is GPL-3.0.\n"
        f"Qt source: https://download.qt.io/archive/qt/{'.'.join(qt.split('.')[:2])}/{qt}/submodules/\n"
        f"PySide source: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v{qt}\n"
        "Rebuild instructions and replacement-library build tooling accompany the application source.\n"
    )

    packages = set()
    for source in json.loads(Path(manifest).read_text()):
        source = Path(source)
        if not str(source).startswith(("/lib/", "/usr/lib/")):
            continue
        candidates = {str(source), str(source.resolve())}
        candidates.update(p.replace("/usr/lib/", "/lib/", 1) for p in list(candidates))
        for candidate in candidates:
            result = subprocess.run(["dpkg-query", "-S", candidate], text=True, capture_output=True)
            if result.returncode == 0:
                packages.update(line.rsplit(": ", 1)[0] for line in result.stdout.splitlines())
                break
    for package in sorted(packages):
        name = package.split(":", 1)[0]
        source = Path("/usr/share/doc") / name / "copyright"
        if not source.is_file():
            raise RuntimeError(f"Missing copyright notice for bundled native package {package}")
        out = licenses / "system-packages" / name / "copyright"
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
    versions = subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Package}=${Version}\\n", *sorted(packages)], text=True
    ) if packages else ""
    (destination / "native-packages.txt").write_text(versions)
    if not any("pdfium" in str(p).lower() for p in (licenses / "python-packages").rglob("*")):
        raise RuntimeError("PDFium license notices were not collected")
    print(f"Collected notices for {len(records)} Python distributions and {len(packages)} native packages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--native-manifest", required=True)
    args = parser.parse_args()
    collect(args.destination, args.native_manifest)
