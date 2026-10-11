# PyInstaller spec: one-file windowed build.  pyinstaller SignBrush.spec
block_cipher = None

a = Analysis(
    ["run_signbrush.py"],
    pathex=[],
    datas=[("signbrush/default_config.json", "signbrush"),
           ("signbrush/gui/fonts", "signbrush/gui/fonts")],
    hiddenimports=["pydirectinput", "mss.windows"],
    excludes=["tkinter", "PyQt6.QtWebEngineCore", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtMultimedia",
              "PyQt6.QtPdf", "PyQt6.Qt3DCore", "matplotlib", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="SignBrush",
    console=False,
    upx=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)
