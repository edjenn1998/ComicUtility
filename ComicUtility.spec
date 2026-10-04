import os
from pathlib import Path
root=Path(os.environ['COMIC_COMPAT_ROOT'])
paths=[root/'lib/x86_64-linux-gnu',root/'usr/lib/x86_64-linux-gnu']
binaries=[]
for path in paths:
    for file in sorted(path.glob('*.so*')):
        if file.is_file() and file.name not in ('libc.so.6','libm.so.6','libpthread.so.0','libdl.so.2','librt.so.1','ld-linux-x86-64.so.2'):
            binaries.append((str(file),'.'))
a=Analysis([str(Path(SPECPATH)/'launch.py')],pathex=[SPECPATH],binaries=binaries,datas=[],hiddenimports=['PIL.AvifImagePlugin','PIL.WebPImagePlugin','PIL.JpegImagePlugin','PIL.PngImagePlugin','PIL.GifImagePlugin','PIL.TiffImagePlugin','pypdfium2_raw'],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['tkinter','psutil'],noarchive=False)
a.binaries=[entry for entry in a.binaries if not (entry[0] in ('libcrypto.so.3','libssl.so.3') or '/tls/' in entry[0] or entry[0].endswith('/libqvnc.so'))]
pyz=PYZ(a.pure)
if os.environ.get('COMIC_BUILD_MODE')=='onedir':
    exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ComicUtility-1.0-Linux-x86_64',debug=False,strip=False,upx=False,console=True)
    coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='ComicUtility-1.0-Linux-x86_64')
else:
    exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='ComicUtility-1.0-Linux-x86_64',debug=False,strip=False,upx=False,console=True)
