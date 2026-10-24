#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "$0")" && pwd)
python_bin=${COMIC_PYTHON:-python3.12}
build_root=${COMIC_BUILD_ROOT:-/tmp/comic-utility-build}
export COMIC_BUILD_ROOT="$build_root"
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Release builds require Python 3.12"'
"$python_bin" -m pip check
"$python_bin" -m PyInstaller --noconfirm --clean \
  --workpath "$build_root/work" --distpath "$build_root/dist" "$project_dir/ComicUtility.spec"
"$python_bin" "$project_dir/tools/check_native_dependencies.py" "$build_root/dist/comic-utility"
"$python_bin" "$project_dir/tools/collect_licenses.py" \
  "$build_root/dist/comic-utility/share" --native-manifest "$build_root/native-sources.json"
QT_QPA_PLATFORM=offscreen "$build_root/dist/comic-utility/comic-utility" --self-test \
  --rar-fixture "$project_dir/tests/fixtures/test_read_format_rar5_compressed.rar"
