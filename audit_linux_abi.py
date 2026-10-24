#!/usr/bin/env python3
"""Report ELF glibc requirements. This does not prove compatibility on every distro."""

import argparse
import json
import re
import subprocess
import struct
from pathlib import Path


def audit(root):
    results = []
    errors = []
    architectures = set()
    checked = 0
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            with p.open("rb") as f:
                header = f.read(20)
                if header[:4] != b"\x7fELF":
                    continue
                endian = "<" if header[5] == 1 else ">"
                machine = struct.unpack(endian + "H", header[18:20])[0]
                architectures.add({62: "x86_64", 183: "aarch64", 3: "i686", 40: "arm"}.get(machine, f"ELF-machine-{machine}"))
            text = subprocess.run(
                ["readelf", "--version-info", str(p)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            checked += 1
        except (OSError, subprocess.SubprocessError, IndexError, struct.error) as exc:
            errors.append({"file": str(p.relative_to(root)), "error": str(exc)})
            continue
        versions = {
            tuple(map(int, m.split(".")))
            for m in re.findall(r"Name: GLIBC_(\d+(?:\.\d+)+)", text)
        }
        if versions:
            results.append(
                {
                    "file": str(p.relative_to(root)),
                    "minimum_glibc": ".".join(map(str, max(versions))),
                }
            )
    highest = max(
        (tuple(map(int, r["minimum_glibc"].split("."))) for r in results), default=()
    )
    return {
        "architecture": ", ".join(sorted(architectures)),
        "minimum_glibc": ".".join(map(str, highest)),
        "elf_files_checked": checked,
        "errors": errors,
        "files": results,
        "limitations": "Symbol audit only. Host display libraries, CPU architecture and hardware access also affect compatibility.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--max-glibc", help="Fail when the audited minimum exceeds this version")
    args = parser.parse_args()
    report = audit(args.directory)
    print(json.dumps(report, indent=2))
    if report["errors"] or not report["elf_files_checked"]:
        raise SystemExit(1)
    if args.max_glibc and tuple(map(int, report["minimum_glibc"].split("."))) > tuple(map(int, args.max_glibc.split("."))):
        raise SystemExit(1)
