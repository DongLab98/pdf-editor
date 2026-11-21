"""PDF 편집기 실행 파일."""
import os
import sys
import warnings

warnings.filterwarnings("ignore")


def main():
    if "--selftest" in sys.argv:
        from pdfeditor.selftest import run
        sys.exit(run())

    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from pdfeditor.fontmgr import app_dir
    from pdfeditor.mainwindow import MainWindow

    app = QApplication(sys.argv)
    # Qt 기본 대화상자(파일 열기, 예/아니오 버튼 등) 한국어 번역
    try:
        from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
        tr = QTranslator(app)
        if tr.load(QLocale("ko_KR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(tr)
    except Exception:
        pass
    app.setApplicationName("PDF 편집기")
    app.setOrganizationName("PdfEditorKR")
    from pdfeditor import theme
    theme.apply(app)
    f = QFont()
    f.setFamilies(["Malgun Gothic", "맑은 고딕", "Segoe UI", "NanumGothic", "Noto Sans CJK KR"])
    f.setPointSizeF(9.5 if sys.platform.startswith("win") else 9)
    app.setFont(f)
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PdfEditorKR.PdfEditor")
        except Exception:
            pass
    icon = os.path.join(app_dir(), "assets", "icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    w = MainWindow()
    w.show()
    for a in sys.argv[1:]:
        if not a.startswith("-") and os.path.exists(a):
            w.open_path(a)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
