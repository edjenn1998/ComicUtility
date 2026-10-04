#!/usr/bin/env python3
"""Report ELF glibc requirements. This does not prove compatibility on every distro."""

import argparse
import json
import re
import subprocess
from pathlib import Path


def audit(root):
    results = []
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        try:
            with p.open("rb") as f:
                if f.read(4) != b"\x7fELF":
                    continue
            text = subprocess.run(
                ["readelf", "--version-info", str(p)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
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
        "architecture": "x86_64",
        "minimum_glibc": ".".join(map(str, highest)),
        "elf_files_checked": len(results),
        "files": results,
        "limitations": "Symbol audit only. Host display libraries, CPU architecture and hardware access also affect compatibility.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), indent=2))
