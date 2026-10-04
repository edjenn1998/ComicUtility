#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt PyInstaller==6.22.3
.venv/bin/python -m PyInstaller --noconfirm --clean --onefile --name "ComicUtility-1.0-Linux-$(uname -m)" --collect-binaries pypdfium2_raw --add-binary "$(ldconfig -p | awk '/libarchive.so.13 /{print $NF;exit}'):." launch.py
