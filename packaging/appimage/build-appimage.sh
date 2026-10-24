#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "$0")/../.." && pwd)
python_bin=${COMIC_PYTHON:-python3.12}
build_root=${COMIC_BUILD_ROOT:-/tmp/comic-utility-build}
export COMIC_BUILD_ROOT="$build_root" COMIC_PYTHON="$python_bin"
version=$("$python_bin" -c "import runpy; print(runpy.run_path('$project_dir/version.py')['VERSION'])")
test -n "$build_root" && test "$build_root" != / && test "$build_root" != "$project_dir"
if [[ $(uname -m) != x86_64 ]]; then
  printf '%s\n' 'This AppImage build targets x86_64 only.' >&2
  exit 1
fi
bash "$project_dir/build.sh"
"$python_bin" "$project_dir/tools/fetch_appimage_tools.py" "$build_root/tools"
# Extract the build tool, so building does not require FUSE either.
(cd "$build_root/tools" && ./appimagetool --appimage-extract)
app_dir=$(mktemp -d "$build_root/ComicUtility.AppDir.XXXXXX")
trap 'rm -rf -- "$app_dir"' EXIT
mkdir -p "$app_dir/usr/lib/comic-utility" "$app_dir/usr/share/comic-utility" "$project_dir/dist"
cp -a "$build_root/dist/comic-utility/." "$app_dir/usr/lib/comic-utility/"
mv "$app_dir/usr/lib/comic-utility/share/"* "$app_dir/usr/share/comic-utility/"
rmdir "$app_dir/usr/lib/comic-utility/share"
cp "$project_dir/packaging/appimage/AppRun" "$app_dir/AppRun"
chmod +x "$app_dir/AppRun"
cp "$project_dir/packaging/appimage/"*.desktop "$project_dir/packaging/appimage/"*.svg "$app_dir/"
ln -s io.github.edjenn1998.ComicUtility.svg "$app_dir/.DirIcon"
"$python_bin" "$project_dir/audit_linux_abi.py" "$app_dir" \
  --max-glibc "${COMIC_MAX_GLIBC:-2.35}" > "$project_dir/dist/abi-audit.json"
cp "$project_dir/dist/abi-audit.json" "$app_dir/usr/share/comic-utility/"
cp "$project_dir/packaging/appimage/toolchain.json" "$app_dir/usr/share/comic-utility/"
mkdir -p "$app_dir/usr/share/comic-utility/licenses/appimage-runtime"
cp "$build_root/tools/"*-license "$app_dir/usr/share/comic-utility/licenses/appimage-runtime/"
QT_QPA_PLATFORM=offscreen "$app_dir/AppRun" --self-test
output="$project_dir/dist/ComicUtility-$version-x86_64.AppImage"
ARCH=x86_64 "$build_root/tools/squashfs-root/AppRun" --no-appstream \
  --runtime-file "$build_root/tools/runtime" "$app_dir" "$output"
chmod +x "$output"
QT_QPA_PLATFORM=offscreen "$output" --appimage-extract-and-run --self-test \
  --rar-fixture "$project_dir/tests/fixtures/test_read_format_rar5_multiple_files_solid.rar"
cp "$app_dir/usr/share/comic-utility/python-dependencies.txt" "$project_dir/dist/"
(cd "$project_dir/dist" && sha256sum "$(basename "$output")" abi-audit.json python-dependencies.txt > SHA256SUMS)
