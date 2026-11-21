"""화면 테마: 색상 팔레트, 선 아이콘(Lucide), 앱 전체 스타일시트."""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap

from .fontmgr import app_dir

ACCENT = "#2563eb"        # 파랑 (강조)
ACCENT_SOFT = "#e8efff"
INK = "#1f2937"           # 기본 글자
INK_SOFT = "#4b5563"      # 아이콘
MUTED = "#6b7280"
LINE = "#e3e6eb"          # 테두리
SURFACE = "#ffffff"
CANVAS_BG = "#e9ebef"     # 문서 뒤 배경
PANEL_BG = "#f6f7f9"

# 변환 아이콘 등 의미 있는 색
C_WORD, C_EXCEL, C_PPT, C_RED, C_GREEN, C_AMBER = "#2b579a", "#1e7145", "#c43e1c", "#dc2626", "#16a34a", "#d97706"

_cache: dict = {}


def _svg(name: str) -> bytes | None:
    p = os.path.join(app_dir(), "assets", "icons", f"{name}.svg")
    try:
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


def icon(name: str, color: str = INK_SOFT, size: int = 24) -> QIcon:
    """Lucide 아이콘을 원하는 색으로. 여러 해상도로 만들어 선명하게."""
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    data = _svg(name)
    ic = QIcon()
    if data:
        try:
            from PySide6.QtSvg import QSvgRenderer
            data = data.replace(b"currentColor", color.encode())
            r = QSvgRenderer(QByteArray(data))
            for s in (16, 20, 24, 28, 32, 48, 64):
                pm = QPixmap(s, s)
                pm.fill(Qt.transparent)
                qp = QPainter(pm)
                qp.setRenderHint(QPainter.Antialiasing)
                r.render(qp, QRectF(0, 0, s, s))
                qp.end()
                ic.addPixmap(pm, QIcon.Normal)
                # 비활성 상태: 연한 회색
                dis = QPixmap(s, s)
                dis.fill(Qt.transparent)
                qp = QPainter(dis)
                qp.setRenderHint(QPainter.Antialiasing)
                r2 = QSvgRenderer(QByteArray(data.replace(color.encode(), b"#c3c8d0")))
                r2.render(qp, QRectF(0, 0, s, s))
                qp.end()
                ic.addPixmap(dis, QIcon.Disabled)
        except Exception:
            pass
    _cache[key] = ic
    return ic


def apply(app):
    """Fusion 스타일 + 밝은 팔레트 + 스타일시트."""
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(PANEL_BG))
    pal.setColor(QPalette.WindowText, QColor(INK))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor("#f3f4f6"))
    pal.setColor(QPalette.Text, QColor(INK))
    pal.setColor(QPalette.Button, QColor(SURFACE))
    pal.setColor(QPalette.ButtonText, QColor(INK))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor("#111827"))
    pal.setColor(QPalette.ToolTipText, QColor("white"))
    pal.setColor(QPalette.PlaceholderText, QColor("#9ca3af"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#9ca3af"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#9ca3af"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#9ca3af"))
    app.setPalette(pal)
    extra = ""
    try:
        from .fontmgr import cache_dir
        d = os.path.join(cache_dir(), "ui")
        os.makedirs(d, exist_ok=True)
        for fname, ic, col in (("close", "x", MUTED), ("close_hover", "x", INK), ("down", "chevron-down", INK_SOFT),
                               ("up", "chevron-up", INK_SOFT), ("down_dis", "chevron-down", "#c3c8d0")):
            p = os.path.join(d, f"{fname}.png")
            icon(ic, col).pixmap(28, 28).save(p)
        cp = os.path.join(d, "close.png").replace("\\", "/")
        ch = os.path.join(d, "close_hover.png").replace("\\", "/")
        dn = os.path.join(d, "down.png").replace("\\", "/")
        up = os.path.join(d, "up.png").replace("\\", "/")
        dd = os.path.join(d, "down_dis.png").replace("\\", "/")
        extra = (f"QTabBar::close-button {{ image: url({cp}); subcontrol-position: right; width: 14px; height: 14px;"
                 f" margin: 2px; border-radius: 4px; }}"
                 f"QTabBar::close-button:hover {{ image: url({ch}); background: #e5e7eb; }}"
                 f"QComboBox {{ padding-right: 22px; }}"
                 f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 20px;"
                 f" border: none; }}"
                 f"QComboBox::down-arrow {{ image: url({dn}); width: 12px; height: 12px; }}"
                 f"QComboBox::down-arrow:disabled {{ image: url({dd}); }}"
                 f"QAbstractSpinBox {{ padding-right: 20px; }}"
                 f"QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px;"
                 f" border: none; border-left: 1px solid {LINE}; border-top-right-radius: 6px; background: #fafbfc; }}"
                 f"QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;"
                 f" width: 18px; border: none; border-left: 1px solid {LINE}; border-bottom-right-radius: 6px;"
                 f" background: #fafbfc; }}"
                 f"QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #eef2f8; }}"
                 f"QAbstractSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}"
                 f"QAbstractSpinBox::down-arrow {{ image: url({dn}); width: 10px; height: 10px; }}"
                 f"QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}")
    except Exception:
        pass
    app.setStyleSheet(STYLESHEET + extra)


STYLESHEET = f"""
* {{ outline: none; }}
QMainWindow {{ background: {PANEL_BG}; }}
QToolTip {{ background: #111827; color: white; border: none; padding: 5px 8px; border-radius: 4px; }}

/* ---------- 리본 ---------- */
#Ribbon {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; }}
#Ribbon QTabWidget::pane {{ border: none; border-top: 1px solid {LINE}; background: {SURFACE}; }}
#Ribbon QTabBar {{ background: {SURFACE}; }}
#Ribbon QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 16px 7px 16px; margin: 0 1px;
    border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
#Ribbon QTabBar::tab:hover {{ color: {INK}; }}
#Ribbon QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
#RibbonPage, #RibbonScroll {{ background: {SURFACE}; border: none; }}
#RibbonScroll QScrollBar:horizontal {{ height: 5px; margin: 0; background: transparent; }}
#RibbonScroll QScrollBar::handle:horizontal {{ background: #dde1e7; border-radius: 2px; }}
#RibbonGroup {{ background: transparent; }}
#RibbonGroupTitle {{ color: #8a919c; font-size: 11px; padding-top: 1px; }}
#RibbonSep {{ background: {LINE}; }}
#RibbonPage QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px;
    color: {INK}; padding: 3px 4px; }}
#RibbonPage QToolButton:hover {{ background: #f1f4f9; border-color: #e3e8f0; }}
#RibbonPage QToolButton:pressed {{ background: #e5ebf5; }}
#RibbonPage QToolButton:checked {{ background: {ACCENT_SOFT}; border-color: #c9d8fb; color: #1d4ed8; }}
#RibbonPage QToolButton:disabled {{ color: #b4bac3; }}
#RibbonPage QToolButton[large="true"] {{ padding: 4px 4px 3px 4px; }}
#RibbonPage QToolButton[small="true"] {{ text-align: left; padding: 2px 8px 2px 4px; }}
#FileButton {{ background: {ACCENT}; color: white; border: none; border-radius: 6px; padding: 5px 14px;
    margin: 4px 6px 4px 8px; font-weight: 600; }}
#FileButton:hover {{ background: #1d4ed8; }}
#FileButton::menu-indicator {{ image: none; width: 0; }}
#SearchBox {{ border: 1px solid {LINE}; border-radius: 15px; padding: 4px 12px; background: #f7f8fa;
    min-width: 210px; margin: 4px 10px 4px 4px; selection-background-color: {ACCENT}; }}
#SearchBox:focus {{ border-color: {ACCENT}; background: white; }}

/* ---------- 문서 탭 ---------- */
#DocTabs QTabBar {{ background: {PANEL_BG}; }}
#DocTabs QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 6px 10px 6px 12px; margin: 4px 0 0 4px;
    border: 1px solid transparent; border-bottom: none; border-top-left-radius: 7px; border-top-right-radius: 7px;
    min-width: 90px; max-width: 260px; }}
#DocTabs QTabBar::tab:hover {{ background: #eceef2; color: {INK}; }}
#DocTabs QTabBar::tab:selected {{ background: {CANVAS_BG}; color: {INK}; border-color: {LINE}; font-weight: 600; }}
#DocTabs::pane {{ border: none; border-top: 1px solid {LINE}; }}

/* ---------- 측면 패널 ---------- */
#SidePanel {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
#SidePanel QTabWidget::pane {{ border: none; border-top: 1px solid {LINE}; }}
#SidePanel QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 6px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }}
#SidePanel QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ACCENT}; }}
#Thumbs {{ background: {SURFACE}; border: none; }}
#Thumbs::item {{ color: {MUTED}; border: 2px solid transparent; border-radius: 6px; padding: 4px; margin: 2px; }}
#Thumbs::item:hover {{ background: #f3f6fb; }}
#Thumbs::item:selected {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: #1d4ed8; }}
#Bookmarks {{ border: none; background: {SURFACE}; }}
#Bookmarks::item {{ padding: 4px 2px; }}
#Bookmarks::item:selected {{ background: {ACCENT_SOFT}; color: #1d4ed8; }}
#PanelButton {{ background: transparent; border: 1px solid {LINE}; border-radius: 5px; padding: 4px 8px; color: {INK}; }}
#PanelButton:hover {{ background: #f3f6fb; }}

/* ---------- 문서 영역 ---------- */
#PageArea, #PageContainer {{ background: {CANVAS_BG}; border: none; }}
#Banner {{ background: #fff8e6; border-bottom: 1px solid #f2e2b3; }}
#Banner QLabel {{ color: #7a5b00; }}

/* ---------- 상태 표시줄 ---------- */
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 2px; }}
QStatusBar QToolButton {{ border: none; border-radius: 4px; padding: 3px; background: transparent; }}
QStatusBar QToolButton:hover {{ background: #eef1f6; }}
QStatusBar QLineEdit, QStatusBar QComboBox {{ border: 1px solid {LINE}; border-radius: 4px; padding: 0px 4px;
    background: white; min-height: 22px; }}
#ZoomSlider::groove:horizontal {{ height: 4px; background: #dfe3ea; border-radius: 2px; }}
#ZoomSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
#ZoomSlider::handle:horizontal {{ background: white; border: 1px solid #9aa4b2; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 6px; }}

/* ---------- 시작 화면 ---------- */
#Home {{ background: {CANVAS_BG}; }}
#HomeLink {{ color: {ACCENT}; border: none; padding: 3px 8px; }}
#HomeLink:hover {{ background: {ACCENT_SOFT}; border-radius: 6px; }}
#AdStrip {{ background: {PANEL_BG}; border-top: 1px solid {LINE}; }}
#HomeTitle {{ color: {INK}; font-size: 26px; font-weight: 700; }}
#HomeSub {{ color: {MUTED}; font-size: 13px; }}
#HomeCard {{ background: white; border: 1px solid {LINE}; border-radius: 12px; color: {INK}; font-size: 13px;
    padding: 10px; }}
#HomeCard:hover {{ border-color: {ACCENT}; background: #fbfcff; }}
#HomeSection {{ color: {INK}; font-weight: 700; font-size: 13px; }}
#RecentList {{ background: white; border: 1px solid {LINE}; border-radius: 10px; padding: 4px; }}
#RecentList::item {{ padding: 8px 8px; border-radius: 6px; color: {INK}; }}
#RecentList::item:hover {{ background: #f3f6fb; }}
#RecentList::item:selected {{ background: {ACCENT_SOFT}; color: {INK}; }}

/* ---------- 일반 위젯 ---------- */
QMenu {{ background: white; border: 1px solid {LINE}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; color: {INK}; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: #1d4ed8; }}
QMenu::item:disabled {{ color: #9ca3af; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}
QPushButton {{ background: white; border: 1px solid #d4d9e1; border-radius: 6px; padding: 5px 14px; color: {INK}; }}
QPushButton:hover {{ background: #f5f7fb; border-color: #b9c3d3; }}
QPushButton:pressed {{ background: #eaeef5; }}
QPushButton:default {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
QPushButton:default:hover {{ background: #1d4ed8; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser {{
    border: 1px solid #d4d9e1; border-radius: 6px; padding: 3px 6px; background: white;
    selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ border: 1px solid {LINE}; selection-background-color: {ACCENT_SOFT};
    selection-color: {INK}; background: white; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 8px; margin-top: 10px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {INK_SOFT}; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 6px; top: -1px; background: white; }}
QTabBar::tab {{ padding: 6px 14px; }}
QDialog {{ background: {PANEL_BG}; }}
QProgressBar {{ border: none; background: #e5e7eb; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c3c9d3; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #9aa4b2; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c3c9d3; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #9aa4b2; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none;
    width: 0; height: 0; }}
QSplitter::handle {{ background: {LINE}; }}
QDockWidget {{ border: none; }}
"""
