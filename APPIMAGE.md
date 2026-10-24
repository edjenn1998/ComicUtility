# Building the AppImage

For download/run instructions, including the no-FUSE fallback, see [README.md](README.md).

## Release environment

Official x86_64 builds use Ubuntu 22.04, Python **3.12.15**, and
`requirements-build.txt`, which pins direct and transitive Python dependencies.
Native libraries come from Ubuntu's maintained packages; their exact versions
are recorded inside each build. This is a documented, repeatable build process,
not a claim of byte-for-byte reproducibility across different system updates.

```sh
sudo apt-get update
sudo apt-get install libarchive13 libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 binutils desktop-file-utils
python3.12 -m venv .venv-build
. .venv-build/bin/activate
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
COMIC_PYTHON="$PWD/.venv-build/bin/python" \
COMIC_BUILD_ROOT=/tmp/comic-utility-build \
bash packaging/appimage/build-appimage.sh
```

Use a clean virtual environment and an unused build directory for a release.
Python 3.12 must already be supplied on Ubuntu 22.04 (CI uses actions/setup-python).
The AppImage tool and static type-2 runtime are downloaded and checked against
`packaging/appimage/toolchain.json`. Upstream's continuous URLs can change: a
checksum mismatch stops the build; review and deliberately repin tools then.
No FUSE installation is needed to build or test: the tool is extracted and final
AppImages are tested using `--appimage-extract-and-run`.

`build.sh` and the AppImage script share `ComicUtility.spec`; `build.sh` alone
produces an inspectable onedir application under `$COMIC_BUILD_ROOT/dist/`.
Current builds no longer use the historical `COMIC_COMPAT_ROOT` setup.

## Build verification and outputs

The script runs the bundled GUI/conversion/RAR self-test, generates license
notices from installed wheels and native packages, inspects ELF files with
`audit_linux_abi.py`, and tests the final AppImage. Failed ELF inspection is an
error. Release builds reject a glibc minimum above **2.35**. For a local native
build on a newer system you may set `COMIC_MAX_GLIBC`, but that does not make the
result compatible with older systems; document and test its actual requirement.

Outputs under `dist/`:

- `ComicUtility-1.1.0-x86_64.AppImage`
- `SHA256SUMS`
- `abi-audit.json`
- `python-dependencies.txt`

The AppImage includes current notices, native dependency inventory, Python
version, and toolchain hashes under `usr/share/comic-utility/`. Its statically
linked runtime includes FUSE userspace support, avoiding the old libfuse2 package
dependency. Restricted kernels can use extraction mode.

GitHub Actions builds every push/PR and supports **Run workflow**. Download the
successful run's `ComicUtility-Linux-x86_64` artifact, verify its checksums and
self-test on a target system, then publish those files as a versioned GitHub
release. Preserve older releases; do not replace their binaries with a different
version. Include corresponding source through the tagged repository.
