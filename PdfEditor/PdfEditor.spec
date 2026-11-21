# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정:  pyinstaller --noconfirm PdfEditor.spec
import sys

block_cipher = None

# 쓰지 않는 Qt 모듈은 빼서 용량을 줄임
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvgWidgets", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer",
    "PySide6.QtWebSockets", "PySide6.QtNetworkAuth",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("tessdata", "tessdata"), ("assets", "assets")],
    hiddenimports=["fontTools.subset", "fontTools.ttLib.tables._c_m_a_p", "PIL.ImageQt", "PySide6.QtPrintSupport",
                   "pdf2docx", "docx", "pptx", "openpyxl", "cv2", "numpy"],
    hookspath=[],
    runtime_hooks=[],
    excludes=QT_EXCLUDES + ["tkinter", "matplotlib", "pandas", "scipy", "IPython", "jedi",
              "pytest", "sympy", "PyQt5", "PyQt6", "fontTools.ufoLib", "fontTools.designspaceLib"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PdfEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    version="version_info.txt" if sys.platform.startswith("win") else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="PdfEditor",
)
