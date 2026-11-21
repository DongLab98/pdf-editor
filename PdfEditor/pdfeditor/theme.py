"""화면 테마: 색상 팔레트, 선 아이콘(Lucide), 앱 전체 스타일시트.

디자인 방향: 윈도우 네이티브 (Fluent·Office 2021 계열)
- 회색 탭 줄 위에 흰 리본 카드, 강조색 한 가지(#0f6cbd), 모서리 4px(버튼·입력칸) / 6px(카드·메뉴·리본)
- 아이콘은 선 1.5px 단색. 색은 파일 형식(워드·엑셀·PPT)과 되돌릴 수 없는 삭제에만 씀
- 글자 대비 4.5:1 이상 (비활성 글자 제외), 키보드 포커스는 강조색 테두리로 표시
"""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap

from .fontmgr import app_dir

# ---------------------------------------------------------------- 색 토큰
ACCENT = "#0f6cbd"          # 강조 (선택·주 버튼·포커스)
ACCENT_HOVER = "#115ea3"    # 강조 위에 마우스 / 연한 강조 바탕 위의 강조 글자 (5.9:1)
ACCENT_SOFT = "#ebf3fc"     # 선택된 항목 바탕
ACCENT_SOFT_LINE = "#b4d6fa"
INK = "#242424"             # 기본 글자
INK_SOFT = "#424242"        # 아이콘
MUTED = "#616161"           # 보조 글자 (흰 바탕 6.2:1, 캔버스 5.4:1)
PLACEHOLDER = "#707070"     # 입력칸 안내 글자 (4.9:1)
DISABLED = "#a8a8a8"        # 비활성 글자 (WCAG 예외)
DISABLED_ICON = "#bdbdbd"
LINE = "#e0e0e0"            # 구조 테두리
INPUT_LINE = "#d1d1d1"      # 입력칸·버튼 테두리
INPUT_LINE_HOVER = "#b3b3b3"
SURFACE = "#ffffff"
HOVER_BG = "#f5f5f5"
PRESSED_BG = "#e6e6e6"
CANVAS_BG = "#f0f0f0"       # 문서 뒤 배경 / 리본 탭 줄
PANEL_BG = "#fafafa"
TOOLTIP_BG = "#242424"
SCROLL_HANDLE = "#c7c7c7"
SCROLL_HANDLE_HOVER = "#8a8a8a"
WARN_BG, WARN_LINE, WARN_TEXT = "#fff8e6", "#f2e2b3", "#7a5b00"   # 스캔 문서 안내 띠

R_SM = 4    # 버튼·입력칸
R_MD = 6    # 카드·메뉴·리본 본문

# 의미 있는 색: 파일 형식과 삭제에만 씀
C_WORD, C_EXCEL, C_PPT, C_RED, C_GREEN, C_AMBER = "#2b579a", "#1e7145", "#c43e1c", "#c42b1c", "#107c10", "#9d5d00"

ICON_STROKE = "1.5"  # Lucide 기본 2px 보다 가늘게 (Fluent 아이콘과 비슷한 무게)

_cache: dict = {}


def _svg(name: str) -> bytes | None:
    p = os.path.join(app_dir(), "assets", "icons", f"{name}.svg")
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data.replace(b'stroke-width="2"', f'stroke-width="{ICON_STROKE}"'.encode())


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
                r2 = QSvgRenderer(QByteArray(data.replace(color.encode(), DISABLED_ICON.encode())))
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
    pal.setColor(QPalette.AlternateBase, QColor(HOVER_BG))
    pal.setColor(QPalette.Text, QColor(INK))
    pal.setColor(QPalette.Button, QColor(SURFACE))
    pal.setColor(QPalette.ButtonText, QColor(INK))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(SURFACE))
    pal.setColor(QPalette.ToolTipBase, QColor(TOOLTIP_BG))
    pal.setColor(QPalette.ToolTipText, QColor(SURFACE))
    pal.setColor(QPalette.PlaceholderText, QColor(PLACEHOLDER))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(DISABLED))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DISABLED))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(DISABLED))
    app.setPalette(pal)
    extra = ""
    try:
        from .fontmgr import cache_dir
        d = os.path.join(cache_dir(), "ui")
        os.makedirs(d, exist_ok=True)
        for fname, ic, col in (("close", "x", MUTED), ("close_hover", "x", INK), ("down", "chevron-down", INK_SOFT),
                               ("up", "chevron-up", INK_SOFT), ("down_dis", "chevron-down", DISABLED_ICON)):
            p = os.path.join(d, f"{fname}.png")
            icon(ic, col).pixmap(28, 28).save(p)
        cp = os.path.join(d, "close.png").replace("\\", "/")
        ch = os.path.join(d, "close_hover.png").replace("\\", "/")
        dn = os.path.join(d, "down.png").replace("\\", "/")
        up = os.path.join(d, "up.png").replace("\\", "/")
        dd = os.path.join(d, "down_dis.png").replace("\\", "/")
        extra = (f"QTabBar::close-button {{ image: url({cp}); subcontrol-position: right; width: 14px; height: 14px;"
                 f" margin: 2px; border-radius: {R_SM}px; }}"
                 f"QTabBar::close-button:hover {{ image: url({ch}); background: {PRESSED_BG}; }}"
                 f"QComboBox {{ padding-right: 22px; }}"
                 f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 20px;"
                 f" border: none; }}"
                 f"QComboBox::down-arrow {{ image: url({dn}); width: 12px; height: 12px; }}"
                 f"QComboBox::down-arrow:disabled {{ image: url({dd}); }}"
                 f"QAbstractSpinBox {{ padding-right: 20px; }}"
                 f"QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px;"
                 f" border: none; border-top-right-radius: {R_SM}px; background: {HOVER_BG}; }}"
                 f"QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;"
                 f" width: 18px; border: none; border-bottom-right-radius: {R_SM}px; background: {HOVER_BG}; }}"
                 f"QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {PRESSED_BG}; }}"
                 f"QAbstractSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}"
                 f"QAbstractSpinBox::down-arrow {{ image: url({dn}); width: 10px; height: 10px; }}"
                 f"QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}")
    except Exception:
        pass
    app.setStyleSheet(STYLESHEET + extra)


STYLESHEET = f"""
QMainWindow {{ background: {PANEL_BG}; }}
QToolTip {{ background: {TOOLTIP_BG}; color: {SURFACE}; border: none; padding: 5px 8px; border-radius: {R_SM}px; }}

/* ---------- 키보드 포커스 (마우스 클릭으로는 생기지 않고 Tab 으로 옮길 때 보임) ---------- */
QToolButton:focus, QPushButton:focus {{ border: 1px solid {ACCENT}; }}
QCheckBox:focus, QRadioButton:focus {{ border: 1px solid {ACCENT}; border-radius: {R_SM}px; }}

/* ---------- 리본: 회색 탭 줄 위의 흰 카드 ---------- */
#Ribbon {{ background: {CANVAS_BG}; border: none; }}
#Ribbon QTabWidget::pane {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: {R_MD}px;
    margin: 0 6px 6px 6px; }}
#Ribbon QTabBar {{ background: {CANVAS_BG}; }}
#Ribbon QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 14px 6px 14px; margin: 0 1px;
    border: none; border-bottom: 3px solid transparent; }}
#Ribbon QTabBar::tab:hover {{ color: {INK}; }}
#Ribbon QTabBar::tab:selected {{ color: {INK}; font-weight: 600; border-bottom: 3px solid {ACCENT}; }}
#RibbonPage, #RibbonScroll {{ background: {SURFACE}; border: none; border-radius: {R_MD}px; }}
#RibbonScroll QScrollBar:horizontal {{ height: 5px; margin: 0; background: transparent; }}
#RibbonScroll QScrollBar::handle:horizontal {{ background: {SCROLL_HANDLE}; border-radius: 2px; }}
#RibbonGroup {{ background: transparent; }}
#RibbonGroupTitle {{ color: {MUTED}; font-size: 12px; padding-top: 1px; }}
#RibbonSep {{ background: {LINE}; }}
#RibbonPage QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {R_SM}px;
    color: {INK}; padding: 3px 4px; }}
#RibbonPage QToolButton:hover {{ background: {HOVER_BG}; border-color: {LINE}; }}
#RibbonPage QToolButton:pressed {{ background: {PRESSED_BG}; }}
#RibbonPage QToolButton:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT_SOFT_LINE}; color: {ACCENT_HOVER}; }}
#RibbonPage QToolButton:disabled {{ color: {DISABLED}; }}
#RibbonPage QToolButton:checked:disabled {{ background: transparent; border-color: transparent; color: {DISABLED}; }}
#RibbonPage QToolButton:focus {{ border-color: {ACCENT}; }}
#RibbonPage QToolButton[large="true"] {{ padding: 4px 4px 3px 4px; }}
#RibbonPage QToolButton[small="true"] {{ text-align: left; padding: 2px 8px 2px 4px; }}
#FileButton {{ background: {ACCENT}; color: {SURFACE}; border: none; border-radius: {R_SM}px; padding: 5px 16px;
    margin: 4px 6px 4px 8px; font-weight: 600; }}
#FileButton:hover {{ background: {ACCENT_HOVER}; }}
#FileButton:focus {{ border: 1px solid {INK}; }}
#FileButton::menu-indicator {{ image: none; width: 0; }}
#SearchBox {{ border: 1px solid {INPUT_LINE}; border-radius: {R_SM}px; padding: 4px 8px; background: {SURFACE};
    min-width: 210px; margin: 4px 10px 4px 4px; selection-background-color: {ACCENT}; }}
#SearchBox:focus {{ border-color: {ACCENT}; }}

/* ---------- 문서 탭 ---------- */
#DocTabs QTabBar {{ background: {PANEL_BG}; }}
#DocTabs QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 6px 10px 6px 12px; margin: 4px 0 0 4px;
    border: 1px solid transparent; border-bottom: none; border-top-left-radius: {R_SM}px;
    border-top-right-radius: {R_SM}px; min-width: 90px; max-width: 260px; }}
#DocTabs QTabBar::tab:hover {{ background: {HOVER_BG}; color: {INK}; }}
#DocTabs QTabBar::tab:selected {{ background: {CANVAS_BG}; color: {INK}; border-color: {LINE}; font-weight: 600; }}
#DocTabs::pane {{ border: none; border-top: 1px solid {LINE}; }}

/* ---------- 측면 패널 ---------- */
#SidePanel {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
#SidePanel QTabWidget::pane {{ border: none; border-top: 1px solid {LINE}; }}
#SidePanel QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 6px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }}
#SidePanel QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ACCENT}; }}
#Thumbs {{ background: {SURFACE}; border: none; }}
#Thumbs::item {{ color: {MUTED}; border: 2px solid transparent; border-radius: {R_MD}px; padding: 4px; margin: 2px; }}
#Thumbs::item:hover {{ background: {HOVER_BG}; }}
#Thumbs::item:selected {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
#Bookmarks {{ border: none; background: {SURFACE}; }}
#Bookmarks::item {{ padding: 4px 2px; }}
#Bookmarks::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_HOVER}; }}
#PanelButton {{ background: transparent; border: 1px solid {LINE}; border-radius: {R_SM}px; padding: 4px 8px; color: {INK}; }}
#PanelButton:hover {{ background: {HOVER_BG}; }}

/* ---------- 문서 영역 ---------- */
#PageArea, #PageContainer {{ background: {CANVAS_BG}; border: none; }}
#Banner {{ background: {WARN_BG}; border-bottom: 1px solid {WARN_LINE}; }}
#Banner QLabel {{ color: {WARN_TEXT}; }}

/* ---------- 상태 표시줄 ---------- */
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 2px; }}
QStatusBar QToolButton {{ border: 1px solid transparent; border-radius: {R_SM}px; padding: 3px; background: transparent; }}
QStatusBar QToolButton:hover {{ background: {HOVER_BG}; }}
QStatusBar QToolButton:focus {{ border-color: {ACCENT}; }}
QStatusBar QLineEdit, QStatusBar QComboBox {{ border: 1px solid {INPUT_LINE}; border-radius: {R_SM}px; padding: 0px 4px;
    background: {SURFACE}; min-height: 22px; }}
#ZoomSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
#ZoomSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
#ZoomSlider::handle:horizontal {{ background: {SURFACE}; border: 1px solid {SCROLL_HANDLE_HOVER}; width: 12px; height: 12px;
    margin: -5px 0; border-radius: 6px; }}

/* ---------- 시작 화면 ---------- */
#Home {{ background: {CANVAS_BG}; }}
#HomeLink {{ color: {ACCENT}; border: 1px solid transparent; padding: 3px 8px; border-radius: {R_SM}px; }}
#HomeLink:hover {{ background: {ACCENT_SOFT}; }}
#HomeLink:focus {{ border-color: {ACCENT}; }}
#AdStrip {{ background: {PANEL_BG}; border-top: 1px solid {LINE}; }}
#HomeTitle {{ color: {INK}; font-size: 24px; font-weight: 600; }}
#HomeSub {{ color: {MUTED}; font-size: 13px; }}
#HomeCard {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: {R_MD}px; color: {INK}; font-size: 13px;
    padding: 10px; }}
#HomeCard:hover {{ border-color: {ACCENT}; background: {SURFACE}; }}
#HomeCard:focus {{ border: 1px solid {ACCENT}; }}
#HomeSection {{ color: {INK}; font-weight: 600; font-size: 13px; }}
#RecentList {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: {R_MD}px; padding: 4px; }}
#RecentList::item {{ padding: 8px 8px; border-radius: {R_SM}px; color: {INK}; }}
#RecentList::item:hover {{ background: {HOVER_BG}; }}
#RecentList::item:selected {{ background: {ACCENT_SOFT}; color: {INK}; }}

/* ---------- 일반 위젯 ---------- */
QMenu {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: {R_MD}px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: {R_SM}px; color: {INK}; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_HOVER}; }}
QMenu::item:disabled {{ color: {DISABLED}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}
QMenu::icon {{ padding-left: 8px; }}
QPushButton {{ background: {SURFACE}; border: 1px solid {INPUT_LINE}; border-radius: {R_SM}px; padding: 5px 14px; color: {INK}; }}
QPushButton:hover {{ background: {HOVER_BG}; border-color: {INPUT_LINE_HOVER}; }}
QPushButton:pressed {{ background: {PRESSED_BG}; }}
QPushButton:default {{ background: {ACCENT}; color: {SURFACE}; border-color: {ACCENT}; }}
QPushButton:default:hover {{ background: {ACCENT_HOVER}; }}
QPushButton:default:focus {{ border: 1px solid {INK}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser {{
    border: 1px solid {INPUT_LINE}; border-radius: {R_SM}px; padding: 3px 6px; background: {SURFACE};
    selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ border: 1px solid {LINE}; selection-background-color: {ACCENT_SOFT};
    selection-color: {INK}; background: {SURFACE}; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: {R_MD}px; margin-top: 10px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {INK_SOFT}; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: {R_MD}px; top: -1px; background: {SURFACE}; }}
QTabBar::tab {{ padding: 6px 14px; }}
QDialog {{ background: {PANEL_BG}; }}
QProgressBar {{ border: none; background: {LINE}; border-radius: {R_SM}px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: {R_SM}px; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SCROLL_HANDLE}; border-radius: {R_SM}px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {SCROLL_HANDLE_HOVER}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL_HANDLE}; border-radius: {R_SM}px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {SCROLL_HANDLE_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none;
    width: 0; height: 0; }}
QSplitter::handle {{ background: {LINE}; }}
QDockWidget {{ border: none; }}
"""
