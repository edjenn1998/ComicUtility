# Release libarchive build

The release library is libarchive 3.6.2 with all Debian 3.6.2-1+deb12u5 security
patches. Its two source archives are included under third_party/; SHA256 hashes
are recorded in libarchive-source.dsc. Extract the original, then extract the
Debian archive into its directory and apply each debian/patches/series patch
using patch -p1 in order.

The library was rebuilt rather than using Debian's binary, to avoid its glibc
2.36 arc4random requirement. Its internal fallback function in
libarchive/archive_random.c was renamed from arc4random_buf to
comic_arc4random_buf to avoid a declaration conflict with newer build headers.
The C integer parser header compatibility below keeps the existing pre-C23
parser interface when building on a newer glibc host:

    #define _GNU_SOURCE 1
    #include <features.h>
    #undef __GLIBC_USE_C2X_STRTOL
    #define __GLIBC_USE_C2X_STRTOL 0

Save this as comic-glibc-compat.h in the source root. With the compatibility
root libraries/headers from compatibility-packages.json and
build-dev-packages.json, configure as follows (substitute actual absolute paths):

    ac_cv_func_arc4random_buf=no ac_cv_func_strlcpy=no ac_cv_func_strlcat=no CPPFLAGS=-I/compat/root/usr/include LDFLAGS=-L/compat/root/usr/lib/x86_64-linux-gnu ./configure --disable-static --disable-bsdtar --disable-bsdcpio --disable-bsdcat --without-openssl --without-nettle --without-xml2 --without-expat --without-iconv --without-lzo2 --disable-acl --disable-xattr
    make -j4 ACLOCAL=true AUTOCONF=true AUTOMAKE=true AUTOHEADER=true CFLAGS='-O2 -include /absolute/source/comic-glibc-compat.h'

The ACLOCAL/AUTOCONF overrides keep the shipped generated build files when
security patches change timestamps. Copy .libs/libarchive.so.13.6.2 into the
compatibility root's usr/lib/x86_64-linux-gnu, retaining libarchive.so.13 symlinks.
Re-run the RAR and CB7 tests using LIBARCHIVE set to that library before packaging.
This build retains zlib/bzip2/lzma/lz4/zstd decoding and excludes crypto-enabled
archive writing. Password-protected comics are not an application feature.

The rest of the compatibility root consists of SHA256-verified Debian bullseye
packages listed in compatibility-packages.json. Their listed download URLs,
versions and hashes permit reconstruction with dpkg-deb -x. The standalone Python
release and SHA256 are listed in python-runtime.txt. Use the pinned Python
packages from build-environment.txt. audit_linux_abi.py records the release's
actual required GLIBC symbols; changing any dependency requires another audit.
