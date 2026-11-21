"""메인 창 — 알PDF 스타일: 리본 메뉴 + 문서 탭 + 연속 보기 + 페이지/책갈피 패널."""
from __future__ import annotations

import os
import traceback

import pymupdf
from PySide6.QtCore import QEvent, QPoint, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QImage, QKeySequence,
                           QPainter, QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QSlider, QApplication, QColorDialog, QComboBox, QDockWidget,
                               QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressDialog,
                               QPushButton, QScrollArea, QStackedWidget, QTabWidget,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import __version__, ads, convert, fontmgr, theme, tools
from .ribbon import RibbonPage, scrollable
from .canvas import (MARKUP_TOOLS, SHAPE_TOOLS, TOOL_ADD_IMAGE, TOOL_ADD_TEXT, TOOL_ARROW, TOOL_ELLIPSE,
                     TOOL_ERASE, TOOL_HAND, TOOL_HIGHLIGHT, TOOL_LINE, TOOL_LINK, TOOL_NOTE, TOOL_PEN, TOOL_PLACE,
                     TOOL_RECT, TOOL_SELECT, TOOL_SELECT_TEXT, TOOL_STRIKE, TOOL_UNDERLINE, PageCanvas)
from .dialogs import CropDialog, ImageAdjustDialog, TextDialog, TextResultDialog
from .engine import IMAGE_EXTS, PdfDocument, ocr_languages
from .inline_editor import InlineTextSession
from .tool_dialogs import (CompressDialog, ConvertDialog, EncryptDialog, FileListDialog, HeaderFooterDialog,
                           HtmlDialog, LinkDialog, MetadataDialog, NewPdfDialog, SignatureDialog, SplitDialog,
                           StampDialog, WatermarkDialog)

APP_NAME = "PDF 편집기"
IMG_FILTER = "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"
OPEN_FILTER = "PDF/이미지 (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;PDF (*.pdf);;" + IMG_FILTER
OFFICE_FILTER = "문서 (*.doc *.docx *.rtf *.odt *.xls *.xlsx *.csv *.ods *.ppt *.pptx *.odp *.hwp *.hwpx *.txt)"

TOOL_DEFAULT_COLORS = {TOOL_HIGHLIGHT: (1, 0.92, 0.2), TOOL_UNDERLINE: (0.1, 0.4, 1), TOOL_STRIKE: (0.9, 0.1, 0.1),
                       TOOL_PEN: (0.9, 0.1, 0.1), TOOL_RECT: (0.9, 0.1, 0.1), TOOL_ELLIPSE: (0.9, 0.1, 0.1),
                       TOOL_LINE: (0.9, 0.1, 0.1), TOOL_ARROW: (0.9, 0.1, 0.1), TOOL_NOTE: (1, 0.85, 0.2)}

_icon_cache: dict = {}


def make_icon(sym: str, color: str, size=40) -> QIcon:
    """색 사각형 + 기호로 만든 단순 아이콘."""
    key = (sym, color, size)
    if key in _icon_cache:
        return _icon_cache[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor(color))
    qp.drawRoundedRect(2, 2, size - 4, size - 4, 9, 9)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * (0.5 if len(sym) <= 1 else 0.36 if len(sym) == 2 else 0.27)))
    qp.setFont(f)
    qp.setPen(QColor("white"))
    qp.drawText(pm.rect(), Qt.AlignCenter, sym)
    qp.end()
    ic = QIcon(pm)
    _icon_cache[key] = ic
    return ic


C_FILE, C_EDIT, C_ANNOT, C_PAGE, C_CONV, C_SEC, C_TOOL, C_VIEW = (
    "#3b6fd8", "#1f9d74", "#e0a100", "#7a55c7", "#d9534f", "#455a64", "#0e8fb5", "#607d8b")


# =============================================================================== 작은 위젯
class PageBox(QLineEdit):
    """현재 페이지 번호 입력칸 (QSpinBox 와 같은 사용법)."""
    from PySide6.QtCore import Signal as _Signal
    valueChanged = _Signal(int)

    def __init__(self):
        super().__init__("1")
        self._max = 1
        self._val = 1
        self.setAlignment(Qt.AlignCenter)
        self.setFixedWidth(44)
        self.returnPressed.connect(self._commit)
        self.editingFinished.connect(lambda: self.setText(str(self._val)))

    def setMaximum(self, n):
        self._max = max(1, n)

    def setMinimum(self, n):
        pass

    def value(self):
        return self._val

    def setValue(self, v):
        self._val = max(1, min(self._max, int(v)))
        self.setText(str(self._val))

    def _commit(self):
        try:
            v = int(self.text().strip())
        except ValueError:
            self.setText(str(self._val))
            return
        self.setValue(v)
        self.valueChanged.emit(self._val)


# =============================================================================== 문서 탭
class PageContainer(QWidget):
    """페이지 뒤에 부드러운 그림자를 그리는 배경."""

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setObjectName("PageContainer")
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(Qt.NoPen)
        clip = ev.rect()
        for c in self.view.canvases:
            if not c.isVisible():
                continue
            g = c.geometry()
            if not g.adjusted(-12, -12, 12, 12).intersects(clip):
                continue
            for i, alpha in ((7, 10), (5, 14), (3, 20), (1, 34)):
                qp.setBrush(QColor(15, 23, 42, alpha))
                qp.drawRoundedRect(g.adjusted(-i, -i + 2, i, i + 2), i + 1, i + 1)
        qp.end()


class DocView(QWidget):
    def __init__(self, main: "MainWindow", pdf: PdfDocument):
        super().__init__()
        self.main, self.pdf = main, pdf
        self.zoom = 1.0
        self.fit_mode = "width"
        self.continuous = True
        self.cur = 0
        self.canvases: list[PageCanvas] = []
        self.search_hits, self.search_idx, self.last_q = [], -1, None
        self.search_rev = -1   # 찾기 결과를 계산했을 때의 pdf.revision
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.banner = QWidget()
        self.banner.setObjectName("Banner")
        self.banner.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 6, 10, 6)
        ic = QLabel()
        ic.setPixmap(theme.icon("scan-text", theme.C_AMBER).pixmap(18, 18))
        bl.addWidget(ic)
        self.banner_label = QLabel("스캔한 문서로 보입니다. 문자인식(OCR)을 하면 글자를 검색·복사·수정할 수 있습니다.")
        btn = QPushButton("문자인식(OCR) 실행")
        btn.clicked.connect(lambda: self.main.run_ocr(True))
        btn.setDefault(True)
        close = QToolButton()
        close.setIcon(theme.icon("x", theme.MUTED))
        close.setAutoRaise(True)
        close.clicked.connect(self.banner.hide)
        bl.addWidget(self.banner_label, 1)
        bl.addWidget(btn)
        bl.addWidget(close)
        self.banner.hide()
        lay.addWidget(self.banner)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("PageArea")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = PageContainer(self)
        self.vbox = QVBoxLayout(self.container)
        self.vbox.setSpacing(18)
        self.vbox.setContentsMargins(24, 20, 24, 24)
        self.vbox.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.scroll.setWidget(self.container)
        lay.addWidget(self.scroll)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.scroll.viewport().installEventFilter(self)
        self.container.installEventFilter(self)
        self._lazy = QTimer(self)
        self._lazy.setSingleShot(True)
        self._lazy.setInterval(40)
        self._lazy.timeout.connect(self.render_visible)

    @property
    def title(self):
        name = os.path.basename(self.pdf.path) if self.pdf.path else "제목 없음"
        return name + (" *" if self.pdf.dirty else "")

    # ---- 페이지 위젯
    def clear_search(self):
        """찾기 결과와 강조 표시를 지움."""
        self.search_hits, self.search_idx, self.last_q = [], -1, None
        self.search_rev = -1
        for c in self.canvases:
            if c.highlights:
                c.highlights = []
                c.update()

    def _drop_stale_search(self):
        """문서가 바뀐 뒤에는 예전 찾기 결과(페이지 번호·위치)를 쓰지 않음."""
        if self.search_hits and self.search_rev != self.pdf.revision:
            self.clear_search()

    def rebuild(self):
        self.main.commit_inline()
        self._drop_stale_search()
        for c in self.canvases:
            c.setParent(None)
            c.deleteLater()
        self.canvases = []
        for p in range(self.pdf.page_count):
            c = PageCanvas()
            c.tool = self.main.tool
            c.line_mode = self.main.line_mode
            self.main.connect_canvas(self, c)
            c.setup(self.pdf, p, self.zoom)
            self.vbox.addWidget(c, 0, Qt.AlignHCenter)
            self.canvases.append(c)
        self.cur = max(0, min(self.cur, self.pdf.page_count - 1))
        self._apply_mode()
        self.apply_fit()
        self._lazy.start()

    def refresh_pages(self, pages=None):
        self._drop_stale_search()
        pages = range(len(self.canvases)) if pages is None else pages
        for p in pages:
            if 0 <= p < len(self.canvases):
                c = self.canvases[p]
                c.setup(self.pdf, p, self.zoom)
                c._restore_selection()
                if self._is_visible(c):
                    c.render()
        self._lazy.start()

    def _apply_mode(self):
        for i, c in enumerate(self.canvases):
            c.setVisible(self.continuous or i == self.cur)

    def _is_visible(self, c):
        if not c.isVisible():
            return False
        vp = self.scroll.viewport()
        top = self.scroll.verticalScrollBar().value()
        y0 = c.y()
        return y0 + c.height() >= top - 400 and y0 <= top + vp.height() + 400

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Wheel and ev.modifiers() & Qt.ControlModifier:
            dy = ev.angleDelta().y() or ev.pixelDelta().y()
            if dy:
                vp = self.scroll.viewport()
                pos = vp.mapFromGlobal(ev.globalPosition().toPoint())
                self.set_zoom(self.zoom * (1.12 ** (dy / 120)), anchor=pos)
                self.main._update_enabled()
            return True
        if t == QEvent.NativeGesture and ev.gestureType() == Qt.ZoomNativeGesture:
            vp = self.scroll.viewport()
            self.set_zoom(self.zoom * (1 + ev.value()), anchor=vp.mapFromGlobal(ev.globalPosition().toPoint()))
            self.main._update_enabled()
            return True
        return False

    def render_visible(self):
        for c in self.canvases:
            if self._is_visible(c):
                if c.stale:
                    c.render()
            elif c.pix is not None and abs(c.pno - self.cur) > 6:
                c.drop()

    def _on_scroll(self, _v):
        if self.continuous and self.canvases:
            mid = self.scroll.verticalScrollBar().value() + self.scroll.viewport().height() // 3
            cur = self.cur
            for c in self.canvases:
                if c.y() <= mid <= c.y() + c.height() + 14:
                    cur = c.pno
                    break
            if cur != self.cur:
                self.cur = cur
                self.main.on_page_changed(self)
        self._lazy.start()

    def goto(self, p, top=True):
        if not (0 <= p < len(self.canvases)):
            return
        self.cur = p
        if not self.continuous:
            self._apply_mode()
            self.scroll.verticalScrollBar().setValue(0)
        else:
            QApplication.processEvents()
            self.scroll.verticalScrollBar().setValue(self.canvases[p].y() - 10)
        self._lazy.start()
        self.main.on_page_changed(self)

    def ensure_visible(self, p, rect):
        c = self.canvases[p]
        vr = c.to_view(rect)
        self.scroll.ensureVisible(int(c.x() + vr.center().x()), int(c.y() + vr.center().y()), 60, 150)

    # ---- 확대
    def set_zoom(self, z, keep_fit=False, anchor: QPoint | None = None):
        """anchor: 이 화면 위치(뷰포트 좌표) 아래의 문서 지점이 그대로 있도록 확대/축소."""
        self.main.commit_inline()
        z = max(0.1, min(8.0, z))
        if not keep_fit:
            self.fit_mode = None
        if abs(z - self.zoom) < 1e-4 and self.canvases and self.canvases[0].width() == int(
                self.pdf.page(0).rect.width * z):
            return
        vp = self.scroll.viewport()
        hb, vb = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        if anchor is None:
            anchor = QPoint(vp.width() // 2, min(vp.height() // 3, 200))
        cp = QPoint(anchor.x() + hb.value(), anchor.y() + vb.value())
        target, fx, fy = None, 0.5, 0.0
        for c in self.canvases:
            if not c.isVisible():
                continue
            g = c.geometry()
            if g.top() - 10 <= cp.y() <= g.bottom() + 10:
                target = c
                fx = min(1.0, max(0.0, (cp.x() - g.x()) / max(1, g.width())))
                fy = min(1.0, max(0.0, (cp.y() - g.y()) / max(1, g.height())))
                break
        self.zoom = z
        for c in self.canvases:
            c.rezoom(z)
        self.vbox.activate()
        self.container.adjustSize()
        QApplication.processEvents()
        if target is not None:
            g = target.geometry()
            hb.setValue(int(g.x() + fx * g.width() - anchor.x()))
            vb.setValue(int(g.y() + fy * g.height() - anchor.y()))
        elif self.continuous and self.canvases:
            vb.setValue(self.canvases[self.cur].y() - 10)
        self._lazy.start(140)

    def apply_fit(self):
        if not self.fit_mode or not self.canvases:
            self.set_zoom(self.zoom, keep_fit=True)
            return
        r = self.pdf.page(self.cur).rect
        vw = self.scroll.viewport().width() - 60
        vh = self.scroll.viewport().height() - 40
        z = vw / r.width if self.fit_mode == "width" else min(vw / r.width, vh / r.height)
        if abs(z - self.zoom) > 0.002 or any(c.width() != int(c.pdf.page(c.pno).rect.width * z) for c in self.canvases[:1]):
            self.set_zoom(z, keep_fit=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)

    def current_canvas(self):
        return self.canvases[self.cur] if self.canvases else None


# =============================================================================== 메인 창
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("PdfEditorKR", "PdfEditor")
        self.tool = TOOL_SELECT
        self.line_mode = self.settings.value("line_mode", False, type=bool)
        self.tool_colors = dict(TOOL_DEFAULT_COLORS)
        self.pen_width = 2.0
        self.pending_place = None  # ("image", path) / ("bytes", png)
        self.para_mode = self.settings.value("para_mode", True, type=bool)
        self.inline: InlineTextSession | None = None
        self.text_clip = None   # (텍스트, 서식 원본 TextItem) — 이 프로그램에서 복사한 텍스트 상자
        self.image_clip = None  # (png bytes, (w, h) pt)
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 920)
        self.setAcceptDrops(True)

        self._build_actions()
        self._build_ribbon()
        self.docs = QTabWidget()
        self.docs.setObjectName("DocTabs")
        self.docs.setTabsClosable(True)
        self.docs.setMovable(True)
        self.docs.setDocumentMode(True)
        self.docs.tabCloseRequested.connect(self.close_tab)
        self.docs.currentChanged.connect(self._tab_changed)
        self.home = self._build_home()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.docs)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        # 리본은 메뉴 위젯 자리(도크 영역보다 위)에 둠 → 창 전체 폭, 문서를 열어 왼쪽 패널이 생겨도 버튼이 움직이지 않음
        self.setMenuWidget(self.ribbon)
        cl.addWidget(self.stack, 1)
        self.ad_strip = ads.AdStrip()
        self.ad_strip.setVisible(False)
        cl.addWidget(self.ad_strip)
        self.stack.currentChanged.connect(lambda i: self._sync_ad_strip())
        ads.manager().changed.connect(self._sync_ad_strip)
        ads.manager().changed.connect(self._sync_links)
        self._sync_links()
        self.setCentralWidget(central)
        self._build_docks()
        self._build_statusbar()
        self._build_menubar()
        # 모든 단축키를 창 전체에 등록 → 어떤 리본 탭이 열려 있어도 동작
        for a in self.findChildren(QAction):
            if not a.shortcut().isEmpty():
                a.setShortcutContext(Qt.WindowShortcut)
                self.addAction(a)
        self._update_enabled()

        self._thumb_timer = QTimer(self)
        self._thumb_timer.timeout.connect(self._render_next_thumb)
        self._thumb_queue: list[int] = []
        fontmgr.SYSTEM_FONTS.build_async()
        self._font_timer = QTimer(self)
        self._font_timer.timeout.connect(self._check_fonts)
        self._font_timer.start(300)
        self.side_dock.setFixedWidth(186)
        self._shown_once = False
        if self.settings.value("ribbon_min", False, type=bool):
            self.set_ribbon_minimized(True)

    # ================================================================ 구성
    def _act(self, text, slot, icon=None, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setToolTip(f"{tip or text}" + (f" ({shortcut})" if shortcut else ""))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        A = self._act
        self.a_open = A("열기", self.open_dialog, ("열", C_FILE), "Ctrl+O", "PDF 또는 이미지 열기")
        self.a_new = A("새 PDF", self.new_pdf, ("새", C_FILE), "Ctrl+N")
        self.a_save = A("저장", self.save, ("저", C_FILE), "Ctrl+S")
        self.a_save_as = A("다른 이름으로", self.save_as, ("다", C_FILE), "Ctrl+Shift+S")
        self.a_print = A("인쇄", self.print_doc, ("인", C_FILE), "Ctrl+P")
        self.a_close = A("닫기", lambda: self.close_tab(self.docs.currentIndex()), None, "Ctrl+W")
        self.a_undo = A("실행 취소", self.undo, ("↶", C_FILE), "Ctrl+Z")
        self.a_redo = A("다시 실행", self.redo, ("↷", C_FILE), "Ctrl+Y")
        self.a_copy = A("복사", self.copy_selection, ("복", C_FILE), "Ctrl+C", "선택한 글자·텍스트 상자·이미지 복사")
        self.a_cut = A("잘라내기", self.cut_selection, ("잘", C_FILE), "Ctrl+X", "선택한 이미지·주석 잘라내기")
        self.a_paste = A("붙여넣기", self.paste, ("붙", C_FILE), "Ctrl+V", "복사한 글자나 이미지를 페이지에 붙여넣기")
        self.a_select_all = A("전체 선택", self.select_all, None, "Ctrl+A", "현재 페이지의 글자 전체 선택")
        self.a_find = A("찾기", lambda: (self.find_edit.setFocus(), self.find_edit.selectAll()), None, "Ctrl+F")
        # 도구 (체크형)
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self.tool_actions = {}
        specs = [
            (TOOL_HAND, "손 도구", ("✋", C_VIEW), "H", "화면 이동, 링크·양식 클릭"),
            (TOOL_SELECT_TEXT, "텍스트 선택", ("I", C_VIEW), "S", "글자를 드래그해 선택·복사"),
            (TOOL_SELECT, "편집", ("편", C_EDIT), "V", "글자를 클릭해 그 자리에서 바로 수정 / 이미지·주석 선택·이동"),
            (TOOL_ADD_TEXT, "텍스트 추가", ("T", C_EDIT), "T", "원하는 위치를 클릭해 텍스트 넣기"),
            (TOOL_ADD_IMAGE, "이미지 추가", ("그", C_EDIT), "I", "영역을 드래그해 이미지 넣기"),
            (TOOL_ERASE, "영역 지우기", ("지", C_EDIT), "E", "드래그한 영역의 내용을 지우기"),
            (TOOL_LINK, "링크", ("🔗", C_EDIT), None, "영역을 드래그해 링크 만들기"),
            (TOOL_HIGHLIGHT, "형광펜", ("형", C_ANNOT), "Ctrl+Shift+H", "글자를 드래그해 형광펜"),
            (TOOL_UNDERLINE, "밑줄", ("U", C_ANNOT), None, "글자를 드래그해 밑줄"),
            (TOOL_STRIKE, "취소선", ("S", C_ANNOT), None, "글자를 드래그해 취소선"),
            (TOOL_NOTE, "메모", ("메", C_ANNOT), None, "클릭한 곳에 메모(말풍선) 달기"),
            (TOOL_PEN, "펜", ("✎", C_ANNOT), None, "자유롭게 그리기"),
            (TOOL_RECT, "사각형", ("□", C_ANNOT), None, "드래그해 사각형"),
            (TOOL_ELLIPSE, "원", ("○", C_ANNOT), None, "드래그해 원"),
            (TOOL_LINE, "선", ("─", C_ANNOT), None, "드래그해 선 (Shift: 수평·수직)"),
            (TOOL_ARROW, "화살표", ("→", C_ANNOT), None, "드래그해 화살표"),
        ]
        for tool, text, icon, sc, tip in specs:
            a = A(text, lambda _c=False, t=tool: self.set_tool(t), icon, sc, tip, checkable=True)
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a
        self.tool_actions[TOOL_SELECT].setChecked(True)
        self.a_sign = A("전자 서명", self.sign, ("서", C_ANNOT), None, "서명을 그리거나 불러와 넣기")
        self.a_stamp = A("도장", self.stamp, ("인", "#c62828"), None, "승인·검토 등 도장 넣기")
        self.a_color = A("색", self.pick_tool_color, ("●", "#888888"), None, "현재 도구의 색")
        self.a_del_annots = A("주석 모두 삭제", self.delete_all_annots, ("✕", C_ANNOT))
        self.a_flatten = A("주석 병합", self.flatten_annots, ("병", C_ANNOT), None,
                           "주석을 페이지에 합쳐 어디서나 똑같이 보이게 (이후 주석 편집 불가)")
        # 페이지
        self.a_rot_l = A("왼쪽 회전", lambda: self.rotate_pages(-90), ("↺", C_PAGE), "Ctrl+Shift+R")
        self.a_rot_r = A("오른쪽 회전", lambda: self.rotate_pages(90), ("↻", C_PAGE), "Ctrl+R")
        self.a_ins_blank = A("빈 페이지", self.insert_blank, ("+", C_PAGE))
        self.a_ins_file = A("파일 삽입", self.insert_file_pages, ("삽", C_PAGE), None, "다른 PDF/이미지를 현재 페이지 뒤에")
        self.a_del_page = A("페이지 삭제", self.delete_pages, ("삭", C_PAGE))
        self.a_extract = A("페이지 추출", self.extract_pages, ("추", C_PAGE))
        self.a_split = A("분할", self.split_pdf, ("분", C_PAGE))
        self.a_merge = A("합치기", self.merge_pdfs, ("합", C_PAGE))
        self.a_pnum = A("페이지 번호", lambda: self.header_footer(0), ("#", C_PAGE))
        self.a_hf = A("머리글/바닥글", lambda: self.header_footer(1), ("머", C_PAGE))
        self.a_wm = A("워터마크", self.watermark, ("W", C_PAGE))
        # 변환
        self.a_to_word = A("PDF→워드", lambda: self.convert_to("word"), ("W", "#2b579a"))
        self.a_to_excel = A("PDF→엑셀", lambda: self.convert_to("excel"), ("X", "#217346"))
        self.a_to_ppt = A("PDF→PPT", lambda: self.convert_to("ppt"), ("P", "#d24726"))
        self.a_to_img = A("PDF→이미지", lambda: self.convert_to("image"), ("JPG", C_CONV))
        self.a_to_txt = A("PDF→텍스트", lambda: self.convert_to("text"), ("TXT", C_CONV))
        self.a_from_img = A("이미지→PDF", self.images_to_pdf, ("IMG", C_CONV))
        self.a_from_office = A("문서→PDF", self.office_to_pdf, ("DOC", C_CONV), None,
                               "워드·엑셀·PPT·한글·텍스트 파일을 PDF로 (해당 프로그램 필요)")
        self.a_extract_img = A("이미지 추출", self.extract_images, ("추", C_CONV))
        # 보안
        self.a_encrypt = A("암호 설정", self.encrypt, ("🔒", C_SEC))
        self.a_decrypt = A("암호 해제", self.decrypt, ("🔓", C_SEC))
        self.a_compress = A("용량 줄이기", self.compress, ("압", C_SEC))
        self.a_meta = A("문서 속성", self.metadata, ("i", C_SEC))
        # 도구
        self.a_ocr_page = A("현재 쪽 OCR", lambda: self.run_ocr(False), ("OCR", C_TOOL), "Ctrl+Shift+O")
        self.a_ocr_all = A("전체 OCR", lambda: self.run_ocr(True), ("ALL", C_TOOL))
        self.a_page_text = A("텍스트 보기", self.show_page_text, ("텍", C_TOOL))
        self.a_compare = A("문서 비교", self.compare_docs, ("비", C_TOOL))
        self.a_bm_add = A("책갈피 추가", self.add_bookmark, ("책", C_TOOL), "Ctrl+B")
        # 보기
        self.a_zoom_in = A("확대", lambda: self.view and self.view.set_zoom(self.view.zoom * 1.2), ("+", C_VIEW), "Ctrl++")
        self.a_zoom_out = A("축소", lambda: self.view and self.view.set_zoom(self.view.zoom / 1.2), ("−", C_VIEW), "Ctrl+-")
        self.a_fit_w = A("폭 맞춤", lambda: self.fit("width"), ("↔", C_VIEW), "Ctrl+1")
        self.a_fit_p = A("쪽 맞춤", lambda: self.fit("page"), ("▣", C_VIEW), "Ctrl+2")
        self.a_cont = A("연속 보기", self.toggle_continuous, ("≡", C_VIEW), None, "페이지를 이어서 / 한 장씩", True)
        self.a_cont.setChecked(True)
        self.a_full = A("전체 화면", self.toggle_fullscreen, ("⛶", C_VIEW), "F11")
        self.a_prev = A("이전 페이지", lambda: self.view and self.view.goto(self.view.cur - 1), None, "PgUp")
        self.a_next = A("다음 페이지", lambda: self.view and self.view.goto(self.view.cur + 1), None, "PgDown")
        self.a_first = A("첫 페이지", lambda: self.view and self.view.goto(0), None, "Ctrl+Home")
        self.a_last = A("마지막 페이지", lambda: self.view and self.view.goto(self.view.pdf.page_count - 1), None, "Ctrl+End")
        for a in (self.a_prev, self.a_next, self.a_first, self.a_last, self.a_copy, self.a_cut, self.a_paste,
                  self.a_select_all, self.a_find, self.a_close):
            self.addAction(a)
        self.a_help = A("사용법", self.help, None, "F1")
        self.a_about = A("정보", self.about)
        self.a_blog = A("사용법 블로그", lambda: self._open_link("blog"), tip="사용법·팁·새 소식을 블로그에서 봅니다")
        self.a_blog.setVisible(False)
        self.a_para = A("문단 단위", self._para_mode_changed, None, None,
                        "켜면 여러 줄 문단을 한 상자로 편집합니다 (자동 줄바꿈)", True)
        self.a_para.setChecked(self.para_mode)
        self.a_line = A("줄 전체", self._line_mode_changed, None, None,
                        "켜면 서식과 관계없이 한 줄 전체를 선택합니다", True)
        self.a_line.setChecked(self.line_mode)
        self.a_panel = A("패널", lambda on: self.side_dock.setVisible(on), None, "F4", "페이지·책갈피 패널 보이기", True)
        self.a_panel.setChecked(True)
        self.a_ribbon_min = A("리본 접기", self.set_ribbon_minimized, None, "Ctrl+F1",
                              "리본을 탭 이름만 남기고 접습니다 (탭을 두 번 클릭해도 됨)", True)
        self.a_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.a_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.a_zoom_out.setShortcuts([QKeySequence("Ctrl+-")])
        self.a_reset_zoom = A("100%", lambda: self.view and (self.view.set_zoom(1.0), self._update_enabled()),
                              None, "Ctrl+0", "실제 크기")
        self._apply_icons()
        self.doc_actions = [a for a in self.__dict__.values() if isinstance(a, QAction) and a not in (
            self.a_open, self.a_new, self.a_merge, self.a_from_img, self.a_from_office, self.a_help, self.a_about,
            self.a_ribbon_min)]  # 리본 접기는 문서가 없어도 쓸 수 있어야 함

    def _apply_icons(self):
        T = theme
        m = {
            "a_open": "folder-open", "a_new": "file-plus", "a_save": "save", "a_save_as": "save-all",
            "a_print": "printer", "a_undo": "undo-2", "a_redo": "redo-2", "a_copy": "copy", "a_cut": "scissors",
            "a_paste": "clipboard-paste", "a_find": "search", "a_close": "x",
            "a_sign": ("signature", "#1d4ed8"), "a_stamp": ("stamp", T.C_RED), "a_del_annots": ("trash-2", T.C_RED),
            "a_flatten": "layers", "a_rot_l": "rotate-ccw", "a_rot_r": "rotate-cw", "a_ins_blank": "file-plus-2",
            "a_ins_file": "file-input", "a_del_page": ("file-minus", T.C_RED), "a_extract": "file-output",
            "a_split": "split", "a_merge": "merge", "a_pnum": "list-ordered", "a_hf": "panel-top", "a_wm": "droplet",
            "a_to_word": ("file-text", T.C_WORD), "a_to_excel": ("file-spreadsheet", T.C_EXCEL),
            "a_to_ppt": ("presentation", T.C_PPT), "a_to_img": ("file-image", "#7c3aed"), "a_to_txt": "file-type",
            "a_from_img": ("images", "#7c3aed"), "a_from_office": ("file-symlink", T.C_WORD),
            "a_extract_img": "image-down", "a_encrypt": ("lock", T.C_AMBER), "a_decrypt": "lock-open",
            "a_compress": "file-archive", "a_meta": "info", "a_ocr_page": ("scan-text", T.ACCENT),
            "a_ocr_all": "scan-line", "a_page_text": "file-search", "a_compare": "git-compare",
            "a_bm_add": "bookmark-plus", "a_zoom_in": "zoom-in", "a_zoom_out": "zoom-out",
            "a_fit_w": "move-horizontal", "a_fit_p": "maximize", "a_cont": "rows-3", "a_full": "maximize-2", "a_ribbon_min": "panel-top",
            "a_prev": "chevron-left", "a_next": "chevron-right", "a_first": "chevrons-left",
            "a_last": "chevrons-right", "a_help": "circle-help", "a_about": "info", "a_blog": "book-open", "a_para": "pilcrow",
            "a_line": "wrap-text", "a_panel": "panel-left", "a_select_all": "text-cursor",
        }
        for attr, spec in m.items():
            a = getattr(self, attr, None)
            if a is None:
                continue
            name, color = (spec, T.INK_SOFT) if isinstance(spec, str) else spec
            a.setIcon(T.icon(name, color))
        tools_icons = {TOOL_HAND: "hand", TOOL_SELECT_TEXT: "text-cursor", TOOL_SELECT: ("square-pen", T.ACCENT),
                       TOOL_ADD_TEXT: "type", TOOL_ADD_IMAGE: "image-plus", TOOL_ERASE: "eraser", TOOL_LINK: "link",
                       TOOL_HIGHLIGHT: ("highlighter", T.C_AMBER), TOOL_UNDERLINE: "underline",
                       TOOL_STRIKE: "strikethrough", TOOL_NOTE: "message-square-text", TOOL_PEN: "pen-line",
                       TOOL_RECT: "square", TOOL_ELLIPSE: "circle", TOOL_LINE: "minus", TOOL_ARROW: "move-up-right"}
        for t, spec in tools_icons.items():
            name, color = (spec, T.INK_SOFT) if isinstance(spec, str) else spec
            self.tool_actions[t].setIcon(T.icon(name, color))
        self._update_color_icon()

    def _update_color_icon(self):
        col = QColor.fromRgbF(*self.tool_colors.get(self.tool, (0.9, 0.1, 0.1)))
        pm = QPixmap(48, 48)
        pm.fill(Qt.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(QColor(0, 0, 0, 60))
        qp.setBrush(col)
        qp.drawEllipse(8, 8, 32, 32)
        qp.end()
        self.a_color.setIcon(QIcon(pm))

    def _build_ribbon(self):
        A = self.tool_actions
        wrap = QWidget()
        wrap.setObjectName("Ribbon")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.setDocumentMode(True)
        wl.addWidget(self.ribbon_tabs)
        width_box = QWidget()
        wv = QHBoxLayout(width_box)
        wv.setContentsMargins(4, 0, 4, 0)
        lab = QLabel("굵기(pt)")
        lab.setStyleSheet("color:#4b5563")
        sp = QComboBox()
        sp.setEditable(True)
        sp.addItems(["0.5", "1", "1.5", "2", "3", "4", "5", "6", "8", "10", "12"])
        sp.setCurrentText(f"{self.pen_width:g}")
        sp.setFixedWidth(66)
        sp.setToolTip("선 굵기 (pt)")

        def _w(t):
            try:
                self._width_changed(max(0.3, min(30.0, float(t.replace("pt", "").strip()))))
            except ValueError:
                pass
        sp.currentTextChanged.connect(_w)
        wv.addWidget(lab)
        wv.addWidget(sp)
        pages = [
            ("홈", [("파일", [self.a_open, self.a_save, [self.a_new, self.a_save_as, self.a_print]]),
                   ("클립보드", [self.a_paste, [self.a_copy, self.a_cut, self.a_select_all]]),
                   ("도구", [A[TOOL_HAND], A[TOOL_SELECT_TEXT], A[TOOL_SELECT]]),
                   ("실행", [[self.a_undo, self.a_redo]]),
                   ("바로 가기", [self.a_merge, self.a_to_word, self.a_ocr_page])]),
            ("편집", [("텍스트·이미지", [A[TOOL_SELECT], A[TOOL_ADD_TEXT], A[TOOL_ADD_IMAGE]]),
                    ("편집 방식", [[self.a_para, self.a_line]]),
                    ("영역", [A[TOOL_ERASE], A[TOOL_LINK]]),
                    ("클립보드", [self.a_paste, [self.a_copy, self.a_cut]]),
                    ("꾸미기", [self.a_wm, [self.a_pnum, self.a_hf]])]),
            ("주석", [("텍스트 표시", [A[TOOL_HIGHLIGHT], [A[TOOL_UNDERLINE], A[TOOL_STRIKE]], A[TOOL_NOTE]]),
                    ("그리기", [A[TOOL_PEN], [A[TOOL_RECT], A[TOOL_ELLIPSE]], [A[TOOL_LINE], A[TOOL_ARROW]]]),
                    ("스타일", [self.a_color, [width_box]]),
                    ("서명", [self.a_sign, self.a_stamp]),
                    ("관리", [[self.a_del_annots, self.a_flatten]])]),
            ("페이지", [("회전", [[self.a_rot_l, self.a_rot_r]]),
                     ("구성", [self.a_ins_blank, self.a_ins_file, self.a_del_page]),
                     ("나누기·합치기", [self.a_extract, self.a_split, self.a_merge]),
                     ("꾸미기", [self.a_pnum, self.a_hf, self.a_wm])]),
            ("변환", [("PDF를 다른 형식으로", [self.a_to_word, self.a_to_excel, self.a_to_ppt, self.a_to_img,
                                          [self.a_to_txt, self.a_extract_img]]),
                    ("PDF로 만들기", [self.a_from_img, self.a_from_office])]),
            ("보안", [("암호", [self.a_encrypt, self.a_decrypt]),
                    ("문서", [self.a_compress, self.a_meta])]),
            ("도구", [("문자인식", [self.a_ocr_page, self.a_ocr_all, self.a_page_text]),
                    ("비교·탐색", [self.a_compare, self.a_bm_add])]),
            ("보기", [("확대/축소", [self.a_zoom_in, self.a_zoom_out, [self.a_fit_w, self.a_fit_p]]),
                    ("화면", [self.a_cont, self.a_full, self.a_panel, self.a_ribbon_min])]),
        ]
        scrolls = []
        for name, groups in pages:
            pg = RibbonPage()
            for title, items in groups:
                pg.add_group(title, items)
            pg.finish()
            sa = scrollable(pg)
            scrolls.append(sa)
            self.ribbon_tabs.addTab(sa, name)
        # 모든 탭의 리본 높이를 같게 → 탭을 바꿔도 그룹 이름 줄과 문서 영역 위치가 그대로
        ribbon_h = max(sa.height() for sa in scrolls)
        for sa in scrolls:
            sa.setFixedHeight(ribbon_h)
        self.ribbon_scrolls = scrolls
        # 탭을 바꾸면 그 탭의 그룹 모양을 지금 폭에 맞춤 / 접힌 리본은 탭을 누르면 펼침, 두 번 누르면 접기·펼치기
        self.ribbon_tabs.currentChanged.connect(lambda i: 0 <= i < len(scrolls) and scrolls[i].refit())
        self._ribbon_min = False
        self._ribbon_just_expanded = False
        self.ribbon_tabs.tabBarClicked.connect(self._ribbon_tab_clicked)
        self.ribbon_tabs.tabBarDoubleClicked.connect(self._ribbon_tab_double_clicked)
        self.file_btn = QToolButton()
        self.file_btn.setObjectName("FileButton")
        self.file_btn.setText("파일")
        self.file_btn.setPopupMode(QToolButton.InstantPopup)
        self.ribbon_tabs.setCornerWidget(self.file_btn, Qt.TopLeftCorner)
        self.find_edit = QLineEdit()
        self.find_edit.setObjectName("SearchBox")
        self.find_edit.setPlaceholderText("문서에서 찾기  (Ctrl+F)")
        self.find_edit.addAction(theme.icon("search", theme.MUTED), QLineEdit.LeadingPosition)
        self.find_edit.returnPressed.connect(self.find_next)
        self.ribbon_tabs.setCornerWidget(self.find_edit, Qt.TopRightCorner)
        self.ribbon = wrap

    def _build_home(self):
        w = QWidget()
        w.setObjectName("Home")
        w.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(w)
        outer.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(6)
        logo = QLabel()
        logo.setPixmap(QIcon(os.path.join(fontmgr.app_dir(), "assets", "icon.png")).pixmap(64, 64))
        logo.setAlignment(Qt.AlignCenter)
        col.addWidget(logo)
        t = QLabel(APP_NAME)
        t.setObjectName("HomeTitle")
        t.setAlignment(Qt.AlignCenter)
        col.addWidget(t)
        sub = QLabel("PDF 파일을 이 창에 끌어다 놓거나, 아래에서 시작하세요")
        sub.setObjectName("HomeSub")
        sub.setAlignment(Qt.AlignCenter)
        col.addWidget(sub)
        bl = QHBoxLayout()
        bl.addStretch()
        self.home_blog = QToolButton()
        self.home_blog.setObjectName("HomeLink")
        self.home_blog.setDefaultAction(self.a_blog)
        self.home_blog.setText("사용법·팁 블로그 보기")
        self.home_blog.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.home_blog.setIconSize(QSize(15, 15))
        self.home_blog.setAutoRaise(True)
        self.home_blog.setCursor(Qt.PointingHandCursor)
        self.a_blog.changed.connect(lambda: (self.home_blog.setText("사용법·팁 블로그 보기"),
                                             self.home_blog.setVisible(self.a_blog.isVisible())))
        bl.addWidget(self.home_blog)
        bl.addStretch()
        col.addLayout(bl)
        col.addSpacing(16)
        cards = QHBoxLayout()
        cards.setSpacing(14)
        cards.addStretch()
        for a, desc in ((self.a_open, "PDF·이미지 열기"), (self.a_new, "빈 문서 만들기"), (self.a_merge, "여러 파일 합치기"),
                        (self.a_from_img, "사진을 PDF로"), (self.a_from_office, "워드·한글을 PDF로")):
            b = QToolButton()
            b.setObjectName("HomeCard")
            b.setDefaultAction(a)
            b.setText(f"{a.text()}\n{desc}")
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(34, 34))
            b.setFixedSize(150, 118)
            b.setCursor(Qt.PointingHandCursor)
            cards.addWidget(b)
            a.changed.connect(lambda b=b, a=a, d=desc: b.setText(f"{a.text()}\n{d}"))
        cards.addStretch()
        col.addLayout(cards)
        col.addSpacing(26)
        rl = QHBoxLayout()
        rl.addStretch()
        rv = QVBoxLayout()
        hdr = QHBoxLayout()
        hic = QLabel()
        hic.setPixmap(theme.icon("history", theme.INK_SOFT).pixmap(16, 16))
        hl = QLabel("최근 파일")
        hl.setObjectName("HomeSection")
        hdr.addWidget(hic)
        hdr.addWidget(hl)
        hdr.addStretch()
        rv.addLayout(hdr)
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("RecentList")
        self.recent_list.setFixedSize(790, 196)
        self.recent_list.setIconSize(QSize(20, 20))
        self.recent_list.itemActivated.connect(self._open_recent_item)
        self.recent_list.itemDoubleClicked.connect(self._open_recent_item)
        rv.addWidget(self.recent_list)
        rl.addLayout(rv)
        rl.addStretch()
        col.addLayout(rl)
        col.addSpacing(18)
        al = QHBoxLayout()
        al.addStretch()
        self.home_ad = ads.AdBanner("home", QSize(790, 98))
        self.home_ad.setFixedWidth(790)
        al.addWidget(self.home_ad)
        al.addStretch()
        col.addLayout(al)
        outer.addLayout(col)
        outer.addStretch(2)
        return w

    def _open_recent_item(self, it):
        """시작 화면의 최근 파일 항목 열기. 항목이 없거나(None) '최근 파일 없음' 안내 줄이면 무시."""
        path = it.data(Qt.UserRole) if it is not None else None
        if path:
            self.open_path(path)

    def _sync_links(self):
        on = bool(ads.manager().link("blog"))
        self.a_blog.setVisible(on)
        self.home_blog.setVisible(on)

    def _open_link(self, key):
        u = ads.manager().link(key)
        if u:
            QDesktopServices.openUrl(QUrl(u))

    def _sync_ad_strip(self):
        on_doc = self.stack.currentWidget() is self.docs
        self.ad_strip.setVisible(on_doc and bool(ads.manager().for_slot("bar")) and not self.ad_strip.banner.dismissed)

    def _build_docks(self):
        self.thumbs = QListWidget()
        self.thumbs.setObjectName("Thumbs")
        self.thumbs.setIconSize(QSize(118, 156))
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setResizeMode(QListWidget.Adjust)
        self.thumbs.setGridSize(QSize(170, 192))
        self.thumbs.setMovement(QListWidget.Snap)
        self.thumbs.setDragDropMode(QAbstractItemView.InternalMove)
        self.thumbs.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.thumbs.setFrameShape(QFrame.NoFrame)
        self.thumbs.itemClicked.connect(lambda it: self.view and self.view.goto(self.thumbs.row(it)))
        self.thumbs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbs.customContextMenuRequested.connect(self._thumb_menu)
        self.thumbs.model().rowsMoved.connect(self._thumb_moved)
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(6, 6, 6, 6)
        self.bm_tree = QTreeWidget()
        self.bm_tree.setObjectName("Bookmarks")
        self.bm_tree.setHeaderHidden(True)
        self.bm_tree.setFrameShape(QFrame.NoFrame)
        self.bm_tree.itemActivated.connect(self._bm_go)
        self.bm_tree.itemClicked.connect(self._bm_go)
        self.bm_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bm_tree.customContextMenuRequested.connect(self._bm_menu)
        bl.addWidget(self.bm_tree)
        row = QHBoxLayout()
        row.setSpacing(4)
        for text, ic, fn in (("책갈피 추가 (Ctrl+B)", "bookmark-plus", self.add_bookmark),
                             ("이름 변경", "square-pen", self._bm_rename), ("삭제", "trash-2", self._bm_delete)):
            b = QToolButton()
            b.setIcon(theme.icon(ic, theme.INK_SOFT))
            b.setToolTip(text)
            b.setObjectName("PanelButton")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        bl.addLayout(row)
        self.side_tabs = QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.tabBar().setExpanding(True)
        self.side_tabs.setIconSize(QSize(15, 15))
        self.side_tabs.addTab(self.thumbs, theme.icon("files", theme.INK_SOFT), "페이지")
        self.side_tabs.addTab(bw, theme.icon("bookmark", theme.INK_SOFT), "책갈피")
        panel = QWidget()
        panel.setObjectName("SidePanel")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.side_tabs)
        self.side_dock = QDockWidget("패널", self)
        self.side_dock.setObjectName("SideDock")
        self.side_dock.setTitleBarWidget(QWidget())
        self.side_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.side_dock.setWidget(panel)
        self.side_dock.setMinimumWidth(176)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.side_dock)
        self.resizeDocks([self.side_dock], [184], Qt.Horizontal)
        # 이전 코드 호환용
        self.thumb_dock = self.bm_dock = self.side_dock

    def _build_statusbar(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.status_label = QLabel()
        sb.addWidget(self.status_label, 1)
        self.font_status = QLabel("글꼴 불러오는 중…")
        sb.addPermanentWidget(self.font_status)

        def tb(action):
            b = QToolButton()
            b.setDefaultAction(action)
            b.setIconSize(QSize(16, 16))
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            return b
        nav = QWidget()
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(8, 0, 8, 0)
        nl.setSpacing(2)
        self.page_spin = PageBox()
        self.page_spin.valueChanged.connect(lambda v: self.view and self.view.goto(v - 1))
        self.page_total = QLabel("/ 0")
        for w in (tb(self.a_first), tb(self.a_prev), self.page_spin, self.page_total, tb(self.a_next), tb(self.a_last)):
            nl.addWidget(w)
        sb.addPermanentWidget(nav)
        zw = QWidget()
        zl = QHBoxLayout(zw)
        zl.setContentsMargins(4, 0, 4, 0)
        zl.setSpacing(2)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setObjectName("ZoomSlider")
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.setValue(100)
        self.zoom_slider.sliderMoved.connect(lambda v: self.view and (self.view.set_zoom(v / 100), self._update_enabled()))
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setFixedWidth(84)
        self.zoom_combo.addItems(["폭 맞춤", "쪽 맞춤", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"])
        self.zoom_combo.textActivated.connect(self._zoom_combo)
        for w in (tb(self.a_zoom_out), self.zoom_slider, tb(self.a_zoom_in), self.zoom_combo, tb(self.a_fit_w), tb(self.a_fit_p)):
            zl.addWidget(w)
        sb.addPermanentWidget(zw)
        lw = QWidget()
        ll = QHBoxLayout(lw)
        ll.setContentsMargins(4, 0, 6, 0)
        ll.setSpacing(4)
        lic = QLabel()
        lic.setPixmap(theme.icon("scan-text", theme.MUTED).pixmap(15, 15))
        lic.setToolTip("문자인식(OCR) 언어")
        self.lang_combo = QComboBox()
        self.lang_combo.setToolTip("문자인식(OCR) 언어")
        langs = ocr_languages()
        opts = (["kor+eng"] if {"kor", "eng"} <= set(langs) else []) + langs
        self.lang_combo.addItems(opts or ["(언어 데이터 없음)"])
        saved = self.settings.value("ocr_lang", "")
        if saved in opts:
            self.lang_combo.setCurrentText(saved)
        ll.addWidget(lic)
        ll.addWidget(self.lang_combo)
        sb.addPermanentWidget(lw)

    def _build_menubar(self):
        m = QMenu(self)
        for a in (self.a_new, self.a_open):
            m.addAction(a)
        self.recent_menu = m.addMenu(theme.icon("history"), "최근 파일")
        m.addSeparator()
        for a in (self.a_save, self.a_save_as, None, self.a_print, None, self.a_meta, self.a_close):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_help)
        m.addAction(self.a_blog)
        m.addAction(self.a_about)
        m.addSeparator()
        m.addAction(theme.icon("log-out"), "끝내기", self.close, QKeySequence("Ctrl+Q"))
        self.file_btn.setMenu(m)
        # menuBar() 를 부르면 메뉴 위젯 자리의 리본이 메뉴 막대로 바뀌므로 호출하지 않음 (메뉴는 [파일] 버튼에 있음)
        self._update_recent()

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._shown_once:
            self._shown_once = True
            # 처음 보일 때 패널 폭을 정한 뒤, 사용자가 조절할 수 있게 풀어 줌
            QTimer.singleShot(400, lambda: (self.side_dock.setMinimumWidth(150), self.side_dock.setMaximumWidth(520),
                                            self.resizeDocks([self.side_dock], [186], Qt.Horizontal)))

    # ================================================================ 캔버스 연결
    def connect_canvas(self, view: DocView, c: PageCanvas):
        c.pen_color = QColor.fromRgbF(*self.tool_colors.get(self.tool, (0.9, 0.1, 0.1)))
        c.pen_width = self.pen_width
        c.textClicked.connect(lambda it, c=c: self.edit_text(c, it))
        c.textContext.connect(lambda it, pos, c=c: self.text_menu(c, it, pos))
        c.imageContext.connect(lambda im, pos, c=c: self.image_menu(c, im, pos))
        c.imageDoubleClicked.connect(lambda im, c=c: self.image_menu(c, im, self.cursor().pos()))
        c.imageMoved.connect(lambda im, r, c=c: self.move_image(c, im, r))
        c.annotContext.connect(lambda a, pos, c=c: self.annot_menu(c, a, pos))
        c.annotMoved.connect(lambda a, r, c=c: self._do(c.pno, lambda: self.view.pdf.move_annot(c.pno, a, r), "주석 이동"))
        c.annotDoubleClicked.connect(lambda a, c=c: self.edit_annot_content(c, a))
        c.widgetClicked.connect(lambda w, c=c: self.fill_widget(c, w))
        c.linkClicked.connect(self.follow_link)
        c.addTextAt.connect(lambda pt, c=c: self.add_text(c, pt))
        c.addTextBox.connect(lambda pt, w, c=c: self.add_text(c, pt, w))
        c.textMoved.connect(lambda it, d, c=c: self._do(c.pno, lambda: self.view.pdf.move_text(c.pno, it, d), "텍스트 이동"))
        c.rectDrawn.connect(lambda tool, r, c=c: self.rect_drawn(c, tool, r))
        c.markupDrawn.connect(lambda kind, rects, txt, c=c: self._do(
            c.pno, lambda: self.view.pdf.add_markup(c.pno, kind, rects, self.tool_colors[self.tool]),
            {"highlight": "형광펜", "underline": "밑줄", "strikeout": "취소선"}[kind]))
        c.textSelected.connect(lambda rects, txt: self.statusBar().showMessage(
            f"{len(txt)}자 선택됨 — Ctrl+C 복사, 우클릭: 형광펜/밑줄/취소선", 5000))
        c.selectionContext.connect(lambda pos, c=c: self.selection_menu(c, pos))
        c.noteAt.connect(lambda pt, c=c: self.add_note(c, pt))
        c.inkDrawn.connect(lambda strokes, c=c: self._do(
            c.pno, lambda: self.view.pdf.add_ink(c.pno, strokes, self.tool_colors[TOOL_PEN], self.pen_width), None))
        c.shapeDrawn.connect(lambda kind, p1, p2, c=c: self._do(
            c.pno, lambda: self.view.pdf.add_shape(c.pno, kind, p1, p2, self.tool_colors[self.tool], self.pen_width), None))
        c.placeAt.connect(lambda r, c=c: self.place_pending(c, r))
        c.hoverInfo.connect(self.status_label.setText)
        c.emptyContext.connect(lambda pt, pos, c=c: self.empty_menu(c, pt, pos))
        c.para_mode = self.para_mode
        c.before_press = self.commit_inline
        c.focused.connect(lambda c=c, v=view: self._canvas_focused(v, c))
        c.panBy.connect(lambda d, v=view: (v.scroll.horizontalScrollBar().setValue(
            v.scroll.horizontalScrollBar().value() - int(d.x())), v.scroll.verticalScrollBar().setValue(
            v.scroll.verticalScrollBar().value() - int(d.y()))))

    def _canvas_focused(self, view, c):
        if view.cur != c.pno:
            view.cur = c.pno
            self.on_page_changed(view)
        for o in view.canvases:
            if o is not c and (o.sel_image or o.sel_annot or o.text_sel):
                o.clear_selection()

    # ================================================================ 상태
    @property
    def view(self) -> DocView | None:
        w = self.docs.currentWidget()
        return w if isinstance(w, DocView) else None

    def _check_fonts(self):
        if fontmgr.SYSTEM_FONTS.ready.is_set():
            self._font_timer.stop()
            self.font_status.setText(f"PC 글꼴 {len(fontmgr.SYSTEM_FONTS.display_list())}개")

    def _wait_fonts(self):
        if not fontmgr.SYSTEM_FONTS.ready.is_set():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                fontmgr.SYSTEM_FONTS.ready.wait(60)
            finally:
                QApplication.restoreOverrideCursor()

    def _update_enabled(self):
        v = self.view
        has = v is not None
        for a in self.doc_actions:
            a.setEnabled(has)
        self.find_edit.setEnabled(has)
        for a in self.tool_actions.values():
            a.setEnabled(has)
        self.side_dock.setVisible(has and self.a_panel.isChecked())
        if has:
            self.a_undo.setEnabled(bool(v.pdf.undo_stack))
            self.a_redo.setEnabled(bool(v.pdf.redo_stack))
            self.page_spin.blockSignals(True)
            self.page_spin.setMaximum(max(1, v.pdf.page_count))
            self.page_spin.setValue(v.cur + 1)
            self.page_spin.blockSignals(False)
            self.page_total.setText(f" / {v.pdf.page_count}")
            idx = self.docs.indexOf(v)
            self.docs.setTabText(idx, v.title)
            self.docs.setTabToolTip(idx, v.pdf.path or "")
            self.setWindowTitle(f"{v.title} - {APP_NAME}")
            self.zoom_combo.setCurrentText({"width": "폭 맞춤", "page": "쪽 맞춤"}.get(v.fit_mode, f"{round(v.zoom * 100)}%"))
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(int(round(v.zoom * 100)))
            self.zoom_slider.blockSignals(False)
        else:
            self.setWindowTitle(APP_NAME)
            self.page_total.setText(" / 0")
        self.stack.setCurrentIndex(1 if self.docs.count() else 0)

    def on_page_changed(self, view):
        if view is not self.view:
            return
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(view.cur + 1)
        self.page_spin.blockSignals(False)
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(view.cur)
        self.thumbs.blockSignals(False)

    def _error(self, title, e):
        traceback.print_exc()
        QMessageBox.critical(self, title, str(e))

    def _busy(self, fn, *a, **kw):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return fn(*a, **kw)
        finally:
            QApplication.restoreOverrideCursor()

    # ================================================================ 문서 열기/저장
    def _add_view(self, pdf: PdfDocument):
        v = DocView(self, pdf)
        i = self.docs.addTab(v, v.title)
        self.docs.setCurrentIndex(i)
        self.stack.setCurrentIndex(1)
        QApplication.processEvents()
        v.rebuild()
        self._tab_changed()
        try:
            p0 = pdf.page(0)
            if not p0.get_text().strip() and p0.get_images():
                v.banner.show()
        except Exception:
            pass
        return v

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "열기", self.settings.value("last_dir", os.path.expanduser("~")), OPEN_FILTER)
        for p in paths:
            self.open_path(p)

    def open_path(self, path):
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, f"파일을 찾을 수 없습니다:\n{path}")
            return
        for i in range(self.docs.count()):
            w = self.docs.widget(i)
            if isinstance(w, DocView) and any(p and os.path.normcase(p) == os.path.normcase(path)
                                              for p in (w.pdf.path, w.pdf.source_path)):
                self.docs.setCurrentIndex(i)
                return
        pdf = PdfDocument()
        try:
            try:
                pdf.open(path)
            except PermissionError:
                pw, ok = QInputDialog.getText(self, "암호", f"'{os.path.basename(path)}'은(는) 암호로 보호되어 있습니다.\n암호:",
                                              QLineEdit.Password)
                if not ok:
                    return
                pdf.open(path, pw)
        except PermissionError:
            QMessageBox.warning(self, APP_NAME, "암호가 맞지 않습니다.")
            return
        except Exception as e:
            self._error("열기 실패", e)
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        self._add_recent(path)
        self._add_view(pdf)

    def open_pdf_object(self, doc: pymupdf.Document, title_path=None):
        pdf = PdfDocument()
        pdf._set_doc(doc)
        pdf.path = title_path
        pdf.dirty = title_path is None
        self._add_view(pdf)

    def new_pdf(self):
        dlg = NewPdfDialog(self)
        if dlg.exec():
            self.open_pdf_object(tools.new_pdf(**dlg.values()))

    def close_tab(self, idx):
        if idx < 0:
            return
        self.commit_inline()
        v = self.docs.widget(idx)
        if isinstance(v, DocView) and not self._confirm_discard(v):
            return
        self.docs.removeTab(idx)
        if isinstance(v, DocView):
            v.deleteLater()
        self._update_enabled()
        if not self.docs.count():
            self.thumbs.clear()
            self.bm_tree.clear()
            self._update_recent()

    def _confirm_discard(self, v: DocView):
        if not v.pdf.dirty:
            return True
        self.docs.setCurrentWidget(v)
        r = QMessageBox.question(self, APP_NAME, f"'{v.title.rstrip(' *')}'의 변경 내용을 저장할까요?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def closeEvent(self, ev):
        self.commit_inline()
        for i in range(self.docs.count()):
            v = self.docs.widget(i)
            if isinstance(v, DocView) and not self._confirm_discard(v):
                ev.ignore()
                return
        ev.accept()

    def save(self):
        self.commit_inline()
        v = self.view
        if not v:
            return False
        # 이미지에서 만든 문서는 같은 이름의 PDF 를 몰래 덮어쓰지 않도록 항상 '다른 이름으로 저장'
        if not v.pdf.path or v.pdf.needs_save_as or os.path.splitext(v.pdf.path)[1].lower() in IMAGE_EXTS:
            return self.save_as()
        if v.pdf.was_encrypted:
            r = QMessageBox.question(self, "저장", "원본은 암호가 걸린 문서입니다. 암호 없이 저장할까요?\n"
                                     "(암호를 유지하려면 [보안 → 암호 설정]을 사용하세요)")
            if r != QMessageBox.Yes:
                return False
            v.pdf.was_encrypted = False
        return self._save_to(v, v.pdf.path)

    def save_as(self):
        self.commit_inline()
        v = self.view
        if not v:
            return False
        start = v.pdf.path or os.path.join(self.settings.value("last_dir", os.path.expanduser("~")), "문서.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", start, "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return self._save_to(v, path)

    def _save_to(self, v, path):
        try:
            self._busy(v.pdf.save, path)
        except Exception as e:
            self._error("저장 실패", e)
            return False
        self._add_recent(path)
        self.statusBar().showMessage(f"저장됨: {path}", 4000)
        self._update_enabled()
        return True

    def _ask_save_path(self, title, suffix, filt, default_name=None):
        v = self.view
        base = os.path.splitext(v.pdf.path)[0] if v and v.pdf.path else os.path.join(
            self.settings.value("last_dir", os.path.expanduser("~")), "문서")
        start = default_name or base + suffix
        path, _ = QFileDialog.getSaveFileName(self, title, start, filt)
        return path

    def _add_recent(self, path):
        rec = [p for p in (self.settings.value("recent", []) or []) if p != path]
        if isinstance(rec, str):
            rec = [rec]
        rec.insert(0, path)
        self.settings.setValue("recent", rec[:15])
        self._update_recent()

    def _update_recent(self):
        rec = self.settings.value("recent", []) or []
        if isinstance(rec, str):
            rec = [rec]
        rec = [p for p in rec if os.path.exists(p)]
        self.recent_menu.clear()
        self.recent_list.clear()
        import datetime
        for p in rec:
            self.recent_menu.addAction(theme.icon("file-text"), os.path.basename(p), lambda _=False, p=p: self.open_path(p))
            try:
                when = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
            except OSError:
                when = ""
            it = QListWidgetItem(theme.icon("file-text", theme.C_RED), f"{os.path.basename(p)}\n{os.path.dirname(p)}   ·   {when}")
            it.setToolTip(p)
            it.setData(Qt.UserRole, p)
            self.recent_list.addItem(it)
        if not rec:
            it = QListWidgetItem("최근에 연 파일이 없습니다")
            it.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(it)
        self.recent_menu.setEnabled(bool(rec))

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if self.view and ev.modifiers() & Qt.ControlModifier:
            for p in paths:
                self._page_op(lambda p=p: self.view.pdf.insert_pdf(self.view.cur, p), self.view.cur + 1)
            return
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            if ext in convert.OFFICE_EXTS or ext == ".txt":
                self._office_one(p)
            else:
                self.open_path(p)

    # ================================================================ 탭/패널
    def _tab_changed(self, *_):
        self.commit_inline()
        v = self.view
        self._rebuild_thumbs()
        self._rebuild_bookmarks()
        self._update_enabled()
        if v:
            v.apply_fit()

    def _rebuild_thumbs(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        v = self.view
        if v:
            for i in range(v.pdf.page_count):
                it = QListWidgetItem(str(i + 1))
                it.setTextAlignment(Qt.AlignHCenter)
                self.thumbs.addItem(it)
            self.thumbs.setCurrentRow(v.cur)
            self._thumb_queue = list(range(v.pdf.page_count))
            self._thumb_timer.start(0)
        self.thumbs.blockSignals(False)

    def _queue_thumb(self, p):
        if p not in self._thumb_queue:
            self._thumb_queue.insert(0, p)
        self._thumb_timer.start(0)

    def _render_next_thumb(self):
        v = self.view
        if not self._thumb_queue or not v:
            self._thumb_timer.stop()
            return
        p = self._thumb_queue.pop(0)
        if p >= v.pdf.page_count or p >= self.thumbs.count():
            return
        page = v.pdf.page(p)
        z = 150 / max(page.rect.width, page.rect.height)
        pm = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
        pm2 = QPixmap.fromImage(img)
        ic = QIcon()
        ic.addPixmap(pm2, QIcon.Normal)
        ic.addPixmap(pm2, QIcon.Selected)  # 선택해도 파랗게 물들지 않게
        self.thumbs.item(p).setIcon(ic)

    def _selected_pages(self):
        v = self.view
        rows = sorted({self.thumbs.row(i) for i in self.thumbs.selectedItems()})
        if len(rows) > 1 and self.thumbs.hasFocus() or (len(rows) > 1 and v.cur in rows):
            return rows
        return [v.cur]

    def _thumb_menu(self, pos):
        if not self.view:
            return
        it = self.thumbs.itemAt(pos)
        if it and not it.isSelected():
            self.thumbs.setCurrentItem(it)
            self.view.goto(self.thumbs.row(it))
        m = QMenu(self)
        for a in (self.a_rot_l, self.a_rot_r, None, self.a_ins_blank, self.a_ins_file, self.a_del_page, None,
                  self.a_extract, self.a_ocr_page):
            m.addSeparator() if a is None else m.addAction(a)
        m.exec(self.thumbs.mapToGlobal(pos))

    def _thumb_moved(self, _parent, start, end, _dest, row):
        v = self.view
        if not v or start != end:
            QTimer.singleShot(0, self._rebuild_thumbs)
            return
        to = row if row < start else row - 1

        def op():
            v.pdf.move_page(start, to)
        QTimer.singleShot(0, lambda: self._page_op(op, to))

    def _rebuild_bookmarks(self):
        self.bm_tree.clear()
        v = self.view
        if not v:
            return
        stack = [(0, self.bm_tree.invisibleRootItem())]
        for lvl, title, page, *_ in v.pdf.doc.get_toc(simple=True):
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            parent = stack[-1][1] if stack else self.bm_tree.invisibleRootItem()
            it = QTreeWidgetItem([title])
            it.setData(0, Qt.UserRole, page - 1)
            parent.addChild(it)
            stack.append((lvl, it))
        self.bm_tree.expandAll()

    def _bm_go(self, it, *_):
        p = it.data(0, Qt.UserRole)
        if self.view and p is not None and p >= 0:
            self.view.goto(p)

    def _toc_from_tree(self):
        toc = []

        def walk(item, lvl):
            for i in range(item.childCount()):
                ch = item.child(i)
                toc.append([lvl, ch.text(0), int(ch.data(0, Qt.UserRole)) + 1])
                walk(ch, lvl + 1)
        walk(self.bm_tree.invisibleRootItem(), 1)
        return toc

    def _save_toc(self):
        v = self.view
        try:
            tools.set_toc(v.pdf, self._toc_from_tree())
        except Exception as e:
            self._error("책갈피 저장 실패", e)
        self._rebuild_bookmarks()
        self._update_enabled()

    def add_bookmark(self):
        v = self.view
        if not v:
            return
        name, ok = QInputDialog.getText(self, "책갈피 추가", f"{v.cur + 1} 페이지 책갈피 이름:", text=f"{v.cur + 1} 페이지")
        if ok and name.strip():
            it = QTreeWidgetItem([name.strip()])
            it.setData(0, Qt.UserRole, v.cur)
            sel = self.bm_tree.currentItem()
            # 페이지 순서에 맞게 최상위에 삽입
            root = self.bm_tree.invisibleRootItem()
            pos = root.childCount()
            for i in range(root.childCount()):
                if root.child(i).data(0, Qt.UserRole) > v.cur:
                    pos = i
                    break
            root.insertChild(pos, it)
            _ = sel
            self._save_toc()
            self.bm_dock.raise_()

    def _bm_rename(self):
        it = self.bm_tree.currentItem()
        if it:
            name, ok = QInputDialog.getText(self, "책갈피 이름 변경", "이름:", text=it.text(0))
            if ok and name.strip():
                it.setText(0, name.strip())
                self._save_toc()

    def _bm_delete(self):
        it = self.bm_tree.currentItem()
        if it:
            (it.parent() or self.bm_tree.invisibleRootItem()).removeChild(it)
            self._save_toc()

    def _bm_menu(self, pos):
        m = QMenu(self)
        m.addAction("추가", self.add_bookmark)
        m.addAction("이름 변경", self._bm_rename)
        m.addAction("삭제", self._bm_delete)
        m.exec(self.bm_tree.mapToGlobal(pos))

    # ================================================================ 보기
    def fit(self, mode):
        v = self.view
        if v:
            v.fit_mode = mode
            v.apply_fit()
            self._update_enabled()

    def _zoom_combo(self, text):
        if text == "폭 맞춤":
            self.fit("width")
        elif text == "쪽 맞춤":
            self.fit("page")
        elif self.view:
            try:
                self.view.set_zoom(float(text.replace("%", "").strip()) / 100)
            except ValueError:
                pass

    def toggle_continuous(self, on):
        v = self.view
        if v:
            v.continuous = on
            v._apply_mode()
            v.goto(v.cur)

    # ---- 리본 접기 (Office 와 같은 동작: 탭 두 번 클릭 / Ctrl+F1)
    def set_ribbon_minimized(self, on: bool):
        on = bool(on)
        self._ribbon_min = on
        # QTabWidget 은 숨긴 페이지 자리도 남기므로, 접을 때는 높이를 탭 줄 높이로 제한
        stack = self.ribbon_tabs.findChild(QStackedWidget)
        if stack is not None:
            stack.setVisible(not on)
        bar_h = max(self.ribbon_tabs.tabBar().sizeHint().height(), self.file_btn.sizeHint().height(),
                    self.find_edit.sizeHint().height())  # 탭 줄 양옆의 [파일] 버튼·찾기 상자도 잘리지 않게
        self.ribbon_tabs.setMaximumHeight(bar_h + 2 if on else 16777215)
        self.a_ribbon_min.blockSignals(True)
        self.a_ribbon_min.setChecked(on)
        self.a_ribbon_min.blockSignals(False)
        self.settings.setValue("ribbon_min", on)

    def _ribbon_tab_clicked(self, _idx):
        if self._ribbon_min:
            self.set_ribbon_minimized(False)
            # 같은 두 번 클릭의 두 번째 신호가 바로 다시 접지 않도록 잠깐 표시
            self._ribbon_just_expanded = True
            QTimer.singleShot(QApplication.doubleClickInterval(),
                              lambda: setattr(self, "_ribbon_just_expanded", False))

    def _ribbon_tab_double_clicked(self, _idx):
        if self._ribbon_just_expanded:
            self._ribbon_just_expanded = False
            return
        self.set_ribbon_minimized(not self._ribbon_min)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.ribbon.show()
        else:
            self.showFullScreen()

    # ================================================================ 도구 선택
    def set_tool(self, tool):
        self.commit_inline()
        self.tool = tool
        if tool in self.tool_actions:
            self.tool_actions[tool].setChecked(True)
        elif self.tool_group.checkedAction():
            self.tool_group.checkedAction().setChecked(False)
        col = self.tool_colors.get(tool)
        if col:
            self._update_color_icon()
        if tool != TOOL_PLACE:
            self.pending_place = None
        for i in range(self.docs.count()):
            v = self.docs.widget(i)
            if isinstance(v, DocView):
                for c in v.canvases:
                    c.tool = tool
                    c.pen_color = QColor.fromRgbF(*(col or (0.9, 0.1, 0.1)))
                    c.pen_width = self.pen_width
                    if tool not in (TOOL_SELECT,):
                        c.sel_image = c.sel_annot = None
                    if tool not in (TOOL_SELECT_TEXT, *MARKUP_TOOLS):
                        c.text_sel, c.text_sel_str = [], ""
                    c.update()
        tips = {TOOL_HAND: "드래그로 화면 이동, 링크·양식 필드를 클릭할 수 있습니다",
                TOOL_SELECT_TEXT: "글자를 드래그해 선택 → Ctrl+C 복사, 우클릭으로 형광펜·밑줄",
                TOOL_SELECT: "글자 클릭 → 수정 / 이미지·주석 클릭 → 선택·이동 / 우클릭 메뉴",
                TOOL_ADD_TEXT: "텍스트를 넣을 위치를 클릭하세요", TOOL_ADD_IMAGE: "이미지를 넣을 영역을 드래그하세요",
                TOOL_ERASE: "지울 영역을 드래그하세요", TOOL_LINK: "링크를 만들 영역을 드래그하세요",
                TOOL_NOTE: "메모를 달 위치를 클릭하세요", TOOL_PEN: "드래그해서 그리세요",
                TOOL_PLACE: "넣을 위치를 클릭하세요 (Esc: 취소)"}
        if tool in MARKUP_TOOLS:
            self.statusBar().showMessage("표시할 글자를 드래그하세요", 5000)
        elif tool in SHAPE_TOOLS:
            self.statusBar().showMessage("드래그해서 그리세요", 5000)
        elif tool in tips:
            self.statusBar().showMessage(tips[tool], 5000)

    def pick_tool_color(self):
        cur = self.tool_colors.get(self.tool, (0.9, 0.1, 0.1))
        c = QColorDialog.getColor(QColor.fromRgbF(*cur), self, "색 선택")
        if c.isValid():
            rgb = (c.redF(), c.greenF(), c.blueF())
            key = self.tool if self.tool in self.tool_colors else TOOL_PEN
            self.tool_colors[key] = rgb
            self.set_tool(self.tool)

    def _width_changed(self, v):
        self.pen_width = v
        self.set_tool(self.tool)

    def _line_mode_changed(self, v):
        self.line_mode = v
        self.settings.setValue("line_mode", v)
        for i in range(self.docs.count()):
            w = self.docs.widget(i)
            if isinstance(w, DocView):
                for c in w.canvases:
                    c.line_mode = v

    def keyPressEvent(self, ev):
        v = self.view
        if v and ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            c = v.current_canvas()
            for cc in v.canvases:
                if cc.sel_image or cc.sel_annot:
                    c = cc
                    break
            if c and c.sel_image:
                im = c.sel_image
                c.clear_selection()
                self._do(c.pno, lambda: v.pdf.delete_image(c.pno, im), "이미지 삭제")
                return
            if c and c.sel_annot:
                a = c.sel_annot
                c.clear_selection()
                self._do(c.pno, lambda: v.pdf.delete_annot(c.pno, a), "주석 삭제")
                return
        if v and ev.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10.0 if ev.modifiers() & Qt.ShiftModifier else 1.0
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(ev.key(), 0.0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(ev.key(), 0.0)
            for c in v.canvases:
                if c.sel_image is not None:
                    r = c.sel_image.bbox + (dx, dy, dx, dy)
                    self.move_image(c, c.sel_image, r)
                    return
                if c.sel_annot is not None and c.sel_annot.movable:
                    a = c.sel_annot
                    self._do(c.pno, lambda: v.pdf.move_annot(c.pno, a, a.bbox + (dx, dy, dx, dy)), None)
                    return
        if ev.key() == Qt.Key_Escape:
            if self.isFullScreen():
                self.toggle_fullscreen()
            if v:
                for c in v.canvases:
                    c.clear_selection()
            if self.tool not in (TOOL_SELECT, TOOL_HAND, TOOL_SELECT_TEXT):
                self.set_tool(TOOL_SELECT)
            return
        super().keyPressEvent(ev)

    # ================================================================ 실행 래퍼
    def _do(self, pno, fn, label="", view=None):
        """view: 작업 대상 문서 탭 (생략하면 현재 탭). 인라인 편집은 탭이 바뀐 뒤에 적용될 수 있어 직접 넘김."""
        self.commit_inline()
        v = view or self.view
        try:
            res = fn()
        except Exception as e:
            self._error(f"{label} 실패" if label else "오류", e)
            return None
        if v is None:
            return res
        v.refresh_pages([pno] if pno is not None else None)
        if v is self.view:  # 썸네일 패널은 현재 탭만 보여 줌
            for p in ([pno] if pno is not None else range(v.pdf.page_count)):
                self._queue_thumb(p)
        else:
            idx = self.docs.indexOf(v)
            if idx >= 0:
                self.docs.setTabText(idx, v.title)
        self._update_enabled()
        if label:
            self.statusBar().showMessage(f"{label} 완료", 3000)
        return res

    def _page_op(self, fn, new_cur=None):
        v = self.view
        try:
            fn()
        except Exception as e:
            self._error("페이지 작업 실패", e)
            return
        if new_cur is not None:
            v.cur = max(0, min(new_cur, v.pdf.page_count - 1))
        v.rebuild()
        self._rebuild_thumbs()
        self._rebuild_bookmarks()
        self._update_enabled()
        QTimer.singleShot(50, lambda: v.goto(v.cur))

    def undo(self):
        self.cancel_inline()
        v = self.view
        if v and v.pdf.undo():
            v.rebuild()
            self._rebuild_thumbs()
            self._rebuild_bookmarks()
            self._update_enabled()

    def redo(self):
        self.cancel_inline()
        v = self.view
        if v and v.pdf.redo():
            v.rebuild()
            self._rebuild_thumbs()
            self._rebuild_bookmarks()
            self._update_enabled()

    # ================================================================ 텍스트
    # ---- 페이지 위 직접 편집 (알PDF 방식)
    def start_inline(self, c, item=None, point=None, text=None, style=None, wrap_width=None):
        self.commit_inline()
        self._wait_fonts()
        v = self.view
        if not v or c not in v.canvases:
            return
        if item is not None:
            # 회전된 글자는 대화상자로 수정
            d = pymupdf.Point(item.direction) * v.pdf.page(c.pno).rotation_matrix - \
                pymupdf.Point(0, 0) * v.pdf.page(c.pno).rotation_matrix
            if abs(d.y) > 1e-3 or d.x < 0:
                self.edit_text_dialog(c, item)
                return
        c.hover = None
        try:
            self.inline = InlineTextSession(self, v, c, item=item, point=point, initial_text=text, style_item=style,
                                            wrap_width=wrap_width)
        except Exception as e:
            self.inline = None
            self._error("텍스트 편집", e)
            return
        self.inline.finished.connect(self._inline_finished)
        self.statusBar().showMessage("입력 후 상자 밖을 클릭하거나 Ctrl+Enter 로 적용, Esc 로 취소합니다. "
                                     "✥ 로 상자 이동, 오른쪽 파란 손잡이로 폭 조절", 8000)

    def _inline_finished(self, applied):
        self.inline = None
        # 텍스트 추가 후에는 편집 도구로 돌아감 (알PDF와 같은 흐름)
        if applied and self.tool == TOOL_ADD_TEXT:
            QTimer.singleShot(0, lambda: self.set_tool(TOOL_SELECT))

    def commit_inline(self):
        s = self.inline
        if s is not None and not s.done:
            s.commit()

    def cancel_inline(self):
        s = self.inline
        if s is not None and not s.done:
            s.cancel()

    def edit_text(self, c, item):
        self.start_inline(c, item=item)

    def edit_text_dialog(self, c, item):
        """고급 수정: 대화상자 방식."""
        self._wait_fonts()
        v = self.view
        dlg = TextDialog(self, v.pdf, c.pno, item, title="텍스트 고급 수정")
        if not dlg.exec():
            return
        val = dlg.values()
        if val["text"] == item.text and abs(val["size"] - item.size) < 0.05 and val["color"] == item.rgb \
                and dlg.font_combo.currentIndex() == 0 and val["fill"] is None:
            return
        res = self._do(c.pno, lambda: v.pdf.replace_text(c.pno, item, val["text"], size=val["size"], color=val["color"],
                                                         chain=val["chain"], fill=val["fill"]), "텍스트 수정")
        if res:
            self.statusBar().showMessage(f"텍스트 수정 완료 — 사용 글꼴: {res.chain_desc}", 6000)

    def add_text(self, c, pt, width=None):
        v = self.view
        self.start_inline(c, point=pt, style=v.pdf.nearby_style(c.pno, pt), wrap_width=width)

    def _para_mode_changed(self, on):
        self.commit_inline()
        self.para_mode = on
        self.settings.setValue("para_mode", on)
        for i in range(self.docs.count()):
            w = self.docs.widget(i)
            if isinstance(w, DocView):
                for c in w.canvases:
                    c.para_mode = on
                    c.update()

    def text_menu(self, c, item, gpos):
        v = self.view
        m = QMenu(self)
        m.addAction("여기서 수정", lambda: self.edit_text(c, item))
        m.addAction("고급 수정…", lambda: self.edit_text_dialog(c, item))
        m.addSeparator()
        m.addAction("복사 (Ctrl+C)", lambda: self._copy_text_item(item))
        m.addAction("잘라내기 (Ctrl+X)", lambda: (self._copy_text_item(item), _delete()))
        pa = m.addAction("붙여넣기 (Ctrl+V)", lambda: self.paste(c, item.bbox.bl + (0, item.size * 0.6)))
        pa.setEnabled(self._clipboard_has_content())

        def _delete():
            fill = v.pdf.sample_colors(c.pno, item.bbox)[0] if (item.invisible or item.on_image) else None
            self._do(c.pno, lambda: v.pdf.delete_text(c.pno, item, fill), "텍스트 삭제")
        m.addAction("삭제", _delete)
        m.addSeparator()
        for kind, label in (("highlight", "형광펜"), ("underline", "밑줄"), ("strikeout", "취소선")):
            tool = {"highlight": TOOL_HIGHLIGHT, "underline": TOOL_UNDERLINE, "strikeout": TOOL_STRIKE}[kind]
            m.addAction(label, lambda k=kind, t=tool: self._do(c.pno, lambda: v.pdf.add_markup(
                c.pno, k, [item.bbox], self.tool_colors[t]), "주석"))
        m.addSeparator()
        info = m.addAction(f"글꼴: {fontmgr.decode_pdf_name(item.font)} · {item.size:.1f}pt" if not item.invisible
                           else "OCR로 인식된 텍스트")
        info.setEnabled(False)
        m.exec(gpos)

    # ---- 복사 · 잘라내기 · 붙여넣기
    def _sel_canvas(self):
        v = self.view
        if not v:
            return None
        for c in v.canvases:
            if c.sel_image or c.sel_annot or c.text_sel_str:
                return c
        return None

    def copy_selection(self):
        c = self._sel_canvas()
        if c is None:
            return
        if c.text_sel_str:
            QApplication.clipboard().setText(c.text_sel_str)
            self.text_clip = None
            self.statusBar().showMessage(f"{len(c.text_sel_str)}자 복사됨", 3000)
        elif c.sel_image:
            self._copy_image(c.sel_image)

    def cut_selection(self):
        c = self._sel_canvas()
        v = self.view
        if c is None:
            return
        if c.sel_image:
            im = c.sel_image
            self._copy_image(im)
            c.clear_selection()
            self._do(c.pno, lambda: v.pdf.delete_image(c.pno, im), "잘라내기")
        elif c.sel_annot:
            a = c.sel_annot
            c.clear_selection()
            self._do(c.pno, lambda: v.pdf.delete_annot(c.pno, a), "잘라내기")
        elif c.text_sel_str:
            self.copy_selection()

    def _copy_text_item(self, item):
        QApplication.clipboard().setText(item.text)
        self.text_clip = (item.text, item)
        self.statusBar().showMessage("텍스트 상자를 복사했습니다 (Ctrl+V 로 같은 서식으로 붙여넣기)", 4000)

    def _copy_image(self, item):
        from PIL.ImageQt import ImageQt
        import io
        try:
            img = self.view.pdf.image_pil(item.xref)
        except Exception as e:
            self._error("복사", e)
            return
        bio = io.BytesIO()
        img.save(bio, "PNG")
        self.image_clip = (bio.getvalue(), (item.bbox.width, item.bbox.height))
        q = QImage(ImageQt(img.convert("RGBA")))
        QApplication.clipboard().setImage(q.copy())
        self.statusBar().showMessage("이미지를 복사했습니다", 3000)

    def _clipboard_has_content(self):
        md = QApplication.clipboard().mimeData()
        return bool(md and (md.hasImage() or (md.hasText() and md.text().strip())))

    def select_all(self):
        v = self.view
        if not v:
            return
        c = v.current_canvas()
        n = len(c.select_all_text())
        self.statusBar().showMessage(f"{c.pno + 1} 페이지 글자 {n}자 선택 — Ctrl+C 로 복사", 4000)

    def _paste_target(self):
        """마우스가 올라가 있는 페이지와 위치, 아니면 현재 보이는 페이지의 위쪽."""
        v = self.view
        from PySide6.QtGui import QCursor
        for c in v.canvases:
            if c.isVisible():
                lp = c.mapFromGlobal(QCursor.pos())
                if c.rect().contains(lp):
                    return c, c.to_pdf(QPointF_(lp))
        c = v.current_canvas()
        top = max(0, v.scroll.verticalScrollBar().value() - c.y())
        return c, c.to_pdf(QPointF_(60 * c.zoom, top + 60 * c.zoom))

    def paste(self, c=None, pt=None):
        v = self.view
        if not v:
            return
        if c is None or pt is None or isinstance(c, bool):
            c, pt = self._paste_target()
        md = QApplication.clipboard().mimeData()
        if md is None:
            return
        if md.hasImage():
            self._paste_image(c, pt, md)
        elif md.hasText() and md.text().strip():
            text = md.text().replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
            style = None
            if self.text_clip and self.text_clip[0] == md.text():
                style = self.text_clip[1]
            if self.tool != TOOL_SELECT:
                self.set_tool(TOOL_SELECT)
            self.start_inline(c, point=pt, text=text, style=style or v.pdf.nearby_style(c.pno, pt))
        else:
            self.statusBar().showMessage("붙여넣을 글자나 이미지가 없습니다", 3000)

    def _paste_image(self, c, pt, md):
        import tempfile
        v = self.view
        if self.image_clip:
            data, (w, h) = self.image_clip
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(data))
            q = QImage(md.imageData())
            if q.isNull() or (q.width(), q.height()) != im.size:
                data = None
        else:
            data = None
        if data is None:
            q = QImage(md.imageData())
            if q.isNull():
                return
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            q.save(path, "PNG")
            pr = v.pdf.page(c.pno).rect
            w, h = q.width() * 0.75, q.height() * 0.75  # 96dpi 기준
            s = min(1.0, pr.width * 0.6 / w, pr.height * 0.6 / h)
            w, h = w * s, h * s
        else:
            fd, path = tempfile.mkstemp(suffix=".png")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        rect = pymupdf.Rect(pt.x, pt.y, pt.x + w, pt.y + h)
        if self.tool != TOOL_SELECT:
            self.set_tool(TOOL_SELECT)
        placed = self._do(c.pno, lambda: v.pdf.insert_image(c.pno, rect, path), "이미지 붙여넣기")
        if placed is not None:
            c.select_after = placed
            c.set_page(v.pdf, c.pno, v.zoom)

    def empty_menu(self, c, pt, gpos):
        m = QMenu(self)
        pa = m.addAction("여기에 붙여넣기 (Ctrl+V)", lambda: self.paste(c, pt))
        pa.setEnabled(self._clipboard_has_content())
        m.addAction("여기에 텍스트 추가", lambda: self.add_text(c, pt))
        m.addSeparator()
        m.addAction("전체 선택 (Ctrl+A)", self.select_all)
        m.exec(gpos)

    def selection_menu(self, c, gpos):
        v = self.view
        rects, txt = list(c.text_sel), c.text_sel_str
        m = QMenu(self)
        m.addAction("복사", lambda: QApplication.clipboard().setText(txt))
        m.addSeparator()
        for kind, label, tool in (("highlight", "형광펜", TOOL_HIGHLIGHT), ("underline", "밑줄", TOOL_UNDERLINE),
                                  ("strikeout", "취소선", TOOL_STRIKE)):
            m.addAction(label, lambda k=kind, t=tool: (c.clear_selection(), self._do(
                c.pno, lambda: v.pdf.add_markup(c.pno, k, rects, self.tool_colors[t]), label)))
        m.addAction("검색", lambda: (self.find_edit.setText(txt.split("\n")[0][:60]), self.find_next()))
        m.exec(gpos)

    # ================================================================ 주석
    def add_note(self, c, pt):
        text, ok = QInputDialog.getMultiLineText(self, "메모", "메모 내용:")
        if ok and text.strip():
            self._do(c.pno, lambda: self.view.pdf.add_note(c.pno, pt, text, self.tool_colors[TOOL_NOTE]), "메모")

    def annot_menu(self, c, a, gpos):
        v = self.view
        m = QMenu(self)
        t = m.addAction(f"{a.name} 주석")
        t.setEnabled(False)
        m.addAction("색 변경…", lambda: self._annot_color(c, a))
        sub = m.addMenu("불투명도")
        for pct in (100, 75, 50, 30):
            sub.addAction(f"{pct}%", lambda p=pct: self._do(c.pno, lambda: v.pdf.set_annot_style(c.pno, a, opacity=p / 100), "주석"))
        if a.name in ("펜", "사각형", "원", "선"):
            sub2 = m.addMenu("선 굵기")
            for w in (1, 2, 3, 5, 8):
                sub2.addAction(f"{w} pt", lambda w=w: self._do(c.pno, lambda: v.pdf.set_annot_style(c.pno, a, width=w), "주석"))
        m.addAction("메모 내용 편집…", lambda: self.edit_annot_content(c, a))
        m.addSeparator()
        m.addAction("삭제 (Del)", lambda: (c.clear_selection(), self._do(c.pno, lambda: v.pdf.delete_annot(c.pno, a), "주석 삭제")))
        m.addAction("이 페이지의 주석 모두 삭제", lambda: (c.clear_selection(), self._do(
            c.pno, lambda: v.pdf.delete_all_annots(c.pno), "주석 삭제")))
        m.exec(gpos)

    def _annot_color(self, c, a):
        v = self.view
        col = QColorDialog.getColor(QColor.fromRgbF(*v.pdf.annot_color(c.pno, a)), self, "주석 색")
        if col.isValid():
            self._do(c.pno, lambda: v.pdf.set_annot_style(c.pno, a, color=(col.redF(), col.greenF(), col.blueF())), "주석")

    def edit_annot_content(self, c, a):
        text, ok = QInputDialog.getMultiLineText(self, "메모 내용", "내용:", a.content)
        if ok:
            self._do(c.pno, lambda: self.view.pdf.set_annot_style(c.pno, a, content=text), "메모 수정")

    def delete_all_annots(self):
        v = self.view
        if QMessageBox.question(self, APP_NAME, "문서의 모든 주석(형광펜, 메모, 도형 등)을 삭제할까요?") == QMessageBox.Yes:
            n = self._do(None, lambda: v.pdf.delete_all_annots(), "주석 삭제")
            self.statusBar().showMessage(f"주석 {n or 0}개 삭제", 4000)

    def flatten_annots(self):
        if QMessageBox.question(self, APP_NAME, "주석을 페이지 내용에 합칠까요?\n어떤 프로그램에서도 똑같이 보이지만, "
                                "이후에는 주석으로 편집할 수 없습니다.") == QMessageBox.Yes:
            self._do(None, lambda: self.view.pdf.flatten_annots(), "주석 병합")

    def fill_widget(self, c, w):
        import pymupdf as P
        v = self.view
        if w.kind in (P.PDF_WIDGET_TYPE_CHECKBOX, P.PDF_WIDGET_TYPE_RADIOBUTTON):
            on = str(w.value) not in ("Off", "", "False", "None")
            self._do(c.pno, lambda: v.pdf.set_widget_value(c.pno, w, not on), "양식 입력")
        elif w.kind in (P.PDF_WIDGET_TYPE_COMBOBOX, P.PDF_WIDGET_TYPE_LISTBOX) and w.choices:
            items = [x if isinstance(x, str) else x[0] for x in w.choices]
            cur = items.index(w.value) if w.value in items else 0
            val, ok = QInputDialog.getItem(self, "양식 입력", w.name or "선택:", items, cur, False)
            if ok:
                self._do(c.pno, lambda: v.pdf.set_widget_value(c.pno, w, val), "양식 입력")
        elif w.kind == P.PDF_WIDGET_TYPE_TEXT:
            val, ok = QInputDialog.getMultiLineText(self, "양식 입력", w.name or "값:", str(w.value or ""))
            if ok:
                self._do(c.pno, lambda: v.pdf.set_widget_value(c.pno, w, val), "양식 입력")

    def follow_link(self, ln):
        if ln.get("uri"):
            if QMessageBox.question(self, "링크", f"다음 주소를 열까요?\n{ln['uri']}") == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(ln["uri"]))
        elif ln.get("page", -1) >= 0 and self.view:
            self.view.goto(ln["page"])

    def sign(self):
        dlg = SignatureDialog(self)
        if dlg.exec() and dlg.result_path:
            self._start_place(("image", dlg.result_path), width=140)

    def stamp(self):
        dlg = StampDialog(self)
        if dlg.exec() and dlg.result_png:
            self._start_place(("bytes", dlg.result_png), width=110)

    def _start_place(self, what, width):
        from PIL import Image
        import io
        img = Image.open(what[1] if what[0] == "image" else io.BytesIO(what[1]))
        h = width * img.height / img.width
        self.set_tool(TOOL_PLACE)
        self.pending_place = what
        for c in self.view.canvases:
            c.place_size = (width, h)

    def place_pending(self, c, rect):
        what = self.pending_place
        if not what:
            return
        v = self.view
        if what[0] == "bytes":
            import tempfile
            fd, path = tempfile.mkstemp(suffix=".png")
            with os.fdopen(fd, "wb") as f:
                f.write(what[1])
        else:
            path = what[1]
        c.select_after = rect
        placed = self._do(c.pno, lambda: v.pdf.insert_image(c.pno, rect, path, keep_proportion=True), "넣기")
        if placed is not None:
            c.select_after = placed
        self.set_tool(TOOL_SELECT)
        c.set_page(v.pdf, c.pno, v.zoom)

    # ================================================================ 이미지
    def move_image(self, c, item, rect):
        c.select_after = rect
        self._do(c.pno, lambda: self.view.pdf.move_image(c.pno, item, rect), "이미지 이동/크기 변경")

    def image_menu(self, c, item, gpos):
        v = self.view
        c.sel_image = item
        c.update()
        m = QMenu(self)
        if not item.xref:
            a = m.addAction("인라인 이미지라 편집할 수 없습니다 (영역 지우기 사용)")
            a.setEnabled(False)
            m.exec(gpos)
            return
        T = lambda op, label, **kw: self._do(c.pno, lambda: v.pdf.transform_image(c.pno, item, op, **kw), label)
        m.addAction("복사 (Ctrl+C)", lambda: self._copy_image(item))
        m.addAction("잘라내기 (Ctrl+X)", lambda: (self._copy_image(item), c.clear_selection(), self._do(
            c.pno, lambda: v.pdf.delete_image(c.pno, item), "잘라내기")))
        m.addSeparator()
        m.addAction("다른 이미지로 교체…", lambda: self._replace_image(c, item))
        m.addSeparator()
        m.addAction("오른쪽으로 90° 회전", lambda: T("rotate_cw", "이미지 회전"))
        m.addAction("왼쪽으로 90° 회전", lambda: T("rotate_ccw", "이미지 회전"))
        m.addAction("좌우 반전", lambda: T("flip_h", "좌우 반전"))
        m.addAction("상하 반전", lambda: T("flip_v", "상하 반전"))
        m.addSeparator()
        m.addAction("자르기…", lambda: self._crop_image(c, item))
        m.addAction("밝기/대비/채도…", lambda: self._adjust_image(c, item))
        m.addAction("흑백으로", lambda: T("gray", "흑백 변환"))
        m.addAction("색 반전", lambda: T("invert", "색 반전"))
        m.addSeparator()
        m.addAction("이미지로 저장…", lambda: self._export_image(item))
        m.addAction("이 페이지 OCR", lambda: self.run_ocr(False))
        m.addSeparator()
        m.addAction("삭제 (Del)", lambda: (c.clear_selection(), self._do(c.pno, lambda: v.pdf.delete_image(c.pno, item), "이미지 삭제")))
        m.exec(gpos)

    def _replace_image(self, c, item):
        p, _ = QFileDialog.getOpenFileName(self, "교체할 이미지", self.settings.value("last_dir", ""), IMG_FILTER)
        if p:
            self._do(c.pno, lambda: self.view.pdf.replace_image(c.pno, item, p), "이미지 교체")

    def _adjust_image(self, c, item):
        try:
            img = self.view.pdf.image_pil(item.xref)
        except Exception as e:
            self._error("이미지 읽기 실패", e)
            return
        dlg = ImageAdjustDialog(self, img)
        if dlg.exec():
            val = dlg.values()
            self._do(c.pno, lambda: self.view.pdf.transform_image(c.pno, item, "adjust", **val), "이미지 보정")

    def _crop_image(self, c, item):
        try:
            img = self.view.pdf.image_pil(item.xref)
        except Exception as e:
            self._error("이미지 읽기 실패", e)
            return
        dlg = CropDialog(self, img)
        if dlg.exec():
            box = dlg.box()
            self._do(c.pno, lambda: self.view.pdf.transform_image(c.pno, item, "crop", box=box), "이미지 자르기")

    def _export_image(self, item):
        p, _ = QFileDialog.getSaveFileName(self, "이미지로 저장", "image.png", "PNG (*.png);;JPEG (*.jpg)")
        if p:
            try:
                self.view.pdf.export_image(item, p)
            except Exception as e:
                self._error("저장 실패", e)

    def rect_drawn(self, c, tool, rect):
        v = self.view
        if tool == TOOL_ADD_IMAGE:
            p, _ = QFileDialog.getOpenFileName(self, "넣을 이미지", self.settings.value("last_dir", ""), IMG_FILTER)
            if p:
                self.set_tool(TOOL_SELECT)
                placed = self._do(c.pno, lambda: v.pdf.insert_image(c.pno, rect, p), "이미지 추가")
                if placed is not None:
                    c.select_after = placed
                    c.set_page(v.pdf, c.pno, v.zoom)
        elif tool == TOOL_ERASE:
            self._do(c.pno, lambda: v.pdf.erase_area(c.pno, rect), "영역 지우기")
        elif tool == TOOL_LINK:
            dlg = LinkDialog(self, v.pdf.page_count)
            if dlg.exec():
                uri, page = dlg.values()
                self._do(c.pno, lambda: v.pdf.add_link(c.pno, rect, uri=uri, page_no=page), "링크 추가")

    # ================================================================ 페이지
    def rotate_pages(self, delta):
        v = self.view
        pages = self._selected_pages()

        def op():
            v.pdf.snapshot()
            for p in pages:
                pg = v.pdf.page(p)
                pg.set_rotation((pg.rotation + delta) % 360)
        self._page_op(op, v.cur)

    def insert_blank(self):
        v = self.view
        self._page_op(lambda: v.pdf.insert_blank(v.cur), v.cur + 1)

    def insert_file_pages(self):
        v = self.view
        p, _ = QFileDialog.getOpenFileName(self, "삽입할 파일", self.settings.value("last_dir", ""), OPEN_FILTER)
        if p:
            self._page_op(lambda: v.pdf.insert_pdf(v.cur, p), v.cur + 1)

    def delete_pages(self):
        v = self.view
        pages = self._selected_pages()
        if len(pages) >= v.pdf.page_count:
            QMessageBox.warning(self, APP_NAME, "모든 페이지를 삭제할 수는 없습니다.")
            return
        label = f"{pages[0] + 1} 페이지" if len(pages) == 1 else f"선택한 {len(pages)}개 페이지"
        if QMessageBox.question(self, APP_NAME, f"{label}를 삭제할까요?") == QMessageBox.Yes:
            def op():
                v.pdf.snapshot()
                v.pdf.doc.delete_pages(pages)
            self._page_op(op, min(pages))

    def extract_pages(self):
        v = self.view
        dlg = ConvertDialog(self, "페이지 추출", v.pdf.page_count, v.cur, note="선택한 페이지를 새 PDF 파일로 저장합니다.")
        if not dlg.exec():
            return
        try:
            pages = dlg.range.pages()
        except ValueError as e:
            self._error("페이지 추출", e)
            return
        path = self._ask_save_path("추출한 페이지 저장", "_추출.pdf", "PDF (*.pdf)")
        if path:
            self._busy(tools.extract_pages, v.pdf.doc, pages, path)
            if QMessageBox.question(self, "페이지 추출", f"{len(pages)}페이지를 저장했습니다. 열어 볼까요?") == QMessageBox.Yes:
                self.open_path(path)

    def split_pdf(self):
        v = self.view
        dlg = SplitDialog(self, v.pdf.page_count)
        if not dlg.exec():
            return
        out = QFileDialog.getExistingDirectory(self, "저장할 폴더", os.path.dirname(v.pdf.path or "") or self.settings.value("last_dir", ""))
        if not out:
            return
        base = os.path.splitext(os.path.basename(v.pdf.path or "문서"))[0]
        mode, val = dlg.values()
        try:
            files = self._busy(tools.split, v.pdf.doc, out, base, mode, val)
        except Exception as e:
            self._error("분할 실패", e)
            return
        self._done_folder(f"{len(files)}개 파일로 나눴습니다.", out)

    def merge_pdfs(self):
        initial = [self.view.pdf.path] if self.view and self.view.pdf.path and not self.view.pdf.dirty else []
        dlg = FileListDialog(self, "PDF 합치기", "PDF/이미지 (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)", initial)
        if not dlg.exec():
            return
        path, _ = QFileDialog.getSaveFileName(self, "합친 파일 저장", os.path.join(
            self.settings.value("last_dir", ""), "합친 문서.pdf"), "PDF (*.pdf)")
        if not path:
            return
        try:
            n = self._busy(tools.merge, dlg.list.paths(), path)
        except Exception as e:
            self._error("합치기 실패", e)
            return
        self.statusBar().showMessage(f"{n}페이지로 합쳤습니다", 4000)
        self.open_path(path)

    def header_footer(self, tab):
        v = self.view
        self._wait_fonts()
        dlg = HeaderFooterDialog(self, v.pdf.page_count, v.cur, tab)
        if dlg.exec():
            try:
                spec, pages = dlg.values()
            except ValueError as e:
                self._error("페이지 범위", e)
                return
            self._do(None, lambda: tools.header_footer(v.pdf, pages, spec), "머리글/바닥글")

    def watermark(self):
        v = self.view
        self._wait_fonts()
        dlg = WatermarkDialog(self, v.pdf.page_count, v.cur)
        if not dlg.exec():
            return
        try:
            kind, opts, pages = dlg.values()
        except ValueError as e:
            self._error("페이지 범위", e)
            return
        if kind == "text":
            if not opts["text"].strip():
                return
            self._do(None, lambda: tools.watermark_text(v.pdf, pages, **opts), "워터마크")
        else:
            if not os.path.exists(opts["image_path"]):
                QMessageBox.warning(self, "워터마크", "이미지 파일을 선택하세요.")
                return
            self._do(None, lambda: tools.watermark_image(v.pdf, pages, **opts), "워터마크")

    # ================================================================ 변환
    def _progress(self, title, total):
        prog = QProgressDialog(title, "취소", 0, total, self)
        prog.setWindowTitle(title)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        QApplication.processEvents()

        def cb(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            QApplication.processEvents()
            return not prog.wasCanceled()
        return prog, cb

    def _done_folder(self, msg, folder):
        r = QMessageBox.question(self, "완료", f"{msg}\n폴더를 열까요?")
        if r == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _done_file(self, msg, path, openable=True):
        r = QMessageBox.question(self, "완료", f"{msg}\n{path}\n\n파일을 열까요?")
        if r == QMessageBox.Yes and openable:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def convert_to(self, kind):
        v = self.view
        titles = {"word": ("PDF → 워드", ".docx", "Word 문서 (*.docx)"), "excel": ("PDF → 엑셀", ".xlsx", "Excel 통합 문서 (*.xlsx)"),
                  "ppt": ("PDF → 파워포인트", ".pptx", "PowerPoint (*.pptx)"), "text": ("PDF → 텍스트", ".txt", "텍스트 (*.txt)"),
                  "image": ("PDF → 이미지", "", "")}
        title, ext, filt = titles[kind]
        notes = {"word": "글꼴·표·이미지·단락을 최대한 유지해 편집 가능한 워드 문서로 바꿉니다. 스캔 문서는 먼저 OCR 하세요.",
                 "excel": "표를 찾아 시트로 옮깁니다. 표 선이 없으면 글자 위치로 칸을 나눕니다.",
                 "ppt": "각 페이지를 슬라이드 한 장으로 만듭니다(보이는 그대로). 페이지 글자는 슬라이드 노트에 들어갑니다.",
                 "text": "글자만 추출합니다.", "image": "각 페이지를 이미지 파일로 저장합니다."}
        dlg = ConvertDialog(self, title, v.pdf.page_count, v.cur, image_opts=(kind == "image"), note=notes[kind])
        if not dlg.exec():
            return
        try:
            pages = dlg.range.pages()
        except ValueError as e:
            self._error(title, e)
            return
        if kind == "image":
            out = QFileDialog.getExistingDirectory(self, "이미지를 저장할 폴더", os.path.dirname(v.pdf.path or "") or "")
            if not out:
                return
            base = os.path.splitext(os.path.basename(v.pdf.path or "page"))[0]
            prog, cb = self._progress(title, len(pages))
            try:
                files = convert.to_images(v.pdf.doc, out, base, pages, dlg.dpi.value(), dlg.fmt.currentText(), cb)
            except Exception as e:
                prog.close()
                self._error(title, e)
                return
            prog.close()
            self._done_folder(f"이미지 {len(files)}개를 저장했습니다.", out)
            return
        path = self._ask_save_path(title, ext, filt)
        if not path:
            return
        prog, cb = self._progress(title + " 변환 중…", len(pages))
        try:
            if kind == "word":
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    convert.to_word(v.pdf.doc.tobytes(), path, pages=pages)
                finally:
                    QApplication.restoreOverrideCursor()
            elif kind == "excel":
                convert.to_excel(v.pdf.doc, path, pages, cb)
            elif kind == "ppt":
                convert.to_ppt(v.pdf.doc, path, pages, progress=cb)
            else:
                convert.to_text(v.pdf.doc, path, pages)
        except Exception as e:
            prog.close()
            self._error(title + " 실패", e)
            return
        prog.close()
        self._done_file("변환했습니다.", path)

    def images_to_pdf(self):
        dlg = FileListDialog(self, "이미지 → PDF", IMG_FILTER, ok="PDF 만들기")
        if not dlg.exec():
            return
        path, _ = QFileDialog.getSaveFileName(self, "PDF 저장", os.path.join(self.settings.value("last_dir", ""), "이미지.pdf"), "PDF (*.pdf)")
        if path:
            try:
                self._busy(convert.images_to_pdf, dlg.list.paths(), path, "A4")
            except Exception as e:
                self._error("변환 실패", e)
                return
            self.open_path(path)

    def office_to_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF로 바꿀 문서", self.settings.value("last_dir", ""), OFFICE_FILTER)
        for p in paths:
            self._office_one(p)

    def _office_one(self, src):
        out = os.path.splitext(src)[0] + ".pdf"
        if os.path.exists(out):
            out = os.path.splitext(src)[0] + "_변환.pdf"
        try:
            if src.lower().endswith(".txt"):
                self._wait_fonts()
                self._busy(convert.text_to_pdf, src, out)
            else:
                self.statusBar().showMessage(f"변환 중: {os.path.basename(src)} (해당 프로그램을 백그라운드로 실행합니다)")
                self._busy(convert.office_to_pdf, src, out)
        except Exception as e:
            self._error("문서 → PDF 변환 실패", e)
            return
        self.open_path(out)

    def extract_images(self):
        v = self.view
        out = QFileDialog.getExistingDirectory(self, "이미지를 저장할 폴더", os.path.dirname(v.pdf.path or "") or "")
        if out:
            n = self._busy(tools.extract_images, v.pdf.doc, out)
            self._done_folder(f"이미지 {n}개를 추출했습니다.", out)

    # ================================================================ 보안
    def encrypt(self):
        v = self.view
        dlg = EncryptDialog(self)
        if not dlg.exec():
            return
        path = self._ask_save_path("암호 설정 파일 저장", "_암호.pdf", "PDF (*.pdf)")
        if path:
            try:
                self._busy(v.pdf.save, path, encrypt=dlg.values())
            except Exception as e:
                self._error("암호 설정 실패", e)
                return
            QMessageBox.information(self, "암호 설정", f"암호를 설정해 저장했습니다.\n{path}")

    def decrypt(self):
        v = self.view
        if not v.pdf.was_encrypted:
            QMessageBox.information(self, "암호 해제", "이 문서에는 암호가 걸려 있지 않습니다.\n"
                                    "암호가 걸린 PDF를 열면(암호 입력) 이 기능으로 암호 없는 파일을 만들 수 있습니다.")
            return
        path = self._ask_save_path("암호 해제한 파일 저장", "_암호해제.pdf", "PDF (*.pdf)")
        if path:
            try:
                self._busy(v.pdf.save, path, encrypt={})
            except Exception as e:
                self._error("암호 해제 실패", e)
                return
            QMessageBox.information(self, "암호 해제", f"암호 없이 저장했습니다.\n{path}")

    def compress(self):
        v = self.view
        size = len(v.pdf.doc.tobytes())
        dlg = CompressDialog(self, size)
        if not dlg.exec():
            return
        path = self._ask_save_path("줄인 파일 저장", "_압축.pdf", "PDF (*.pdf)")
        if path:
            try:
                self._busy(v.pdf.save, path, compress=dlg.level())
            except Exception as e:
                self._error("용량 줄이기 실패", e)
                return
            new = os.path.getsize(path)
            QMessageBox.information(self, "용량 줄이기", f"{size / 1024 / 1024:.2f} MB → {new / 1024 / 1024:.2f} MB "
                                    f"({(1 - new / max(size, 1)) * 100:.0f}% 감소)\n{path}")

    def metadata(self):
        v = self.view
        doc = v.pdf.doc
        info = f"페이지: {len(doc)} · PDF 버전: {doc.metadata.get('format', '')} · 암호: {'있음' if v.pdf.was_encrypted else '없음'}"
        dlg = MetadataDialog(self, tools.get_metadata(doc), info)
        if dlg.exec():
            self._do(None, lambda: tools.set_metadata(v.pdf, dlg.values()), "문서 속성")

    # ================================================================ 인쇄
    def print_doc(self):
        v = self.view
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except Exception as e:
            self._error("인쇄", e)
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(v.title)
        printer.setFromTo(1, v.pdf.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("인쇄")
        dlg.setMinMax(1, v.pdf.page_count)
        dlg.setOption(QPrintDialog.PrintCurrentPage, True)
        if not dlg.exec():
            return
        if printer.printRange() == QPrinter.PageRange:
            pages = list(range(printer.fromPage() - 1, printer.toPage()))
        elif printer.printRange() == QPrinter.CurrentPage:
            pages = [v.cur]
        else:
            pages = list(range(v.pdf.page_count))
        prog, cb = self._progress("인쇄 중…", len(pages))
        qp = QPainter()
        if not qp.begin(printer):
            prog.close()
            QMessageBox.warning(self, "인쇄", "프린터를 시작할 수 없습니다.")
            return
        try:
            dpi = min(printer.resolution(), 300)
            for i, p in enumerate(pages):
                if i:
                    printer.newPage()
                page = v.pdf.page(p)
                pm = page.get_pixmap(dpi=dpi, alpha=False)
                img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888)
                area = qp.viewport()
                s = min(area.width() / img.width(), area.height() / img.height())
                w, h = int(img.width() * s), int(img.height() * s)
                qp.drawImage(QRectF_((area.width() - w) / 2, (area.height() - h) / 2, w, h), img)
                if not cb(i + 1, len(pages)):
                    break
        finally:
            qp.end()
            prog.close()
        self.statusBar().showMessage("인쇄를 보냈습니다", 4000)

    # ================================================================ 찾기
    def find_next(self):
        v = self.view
        q = self.find_edit.text().strip()
        if not v or not q:
            return
        if v.last_q != q or not v.search_hits or v.search_rev != v.pdf.revision:
            v.last_q = q
            # 페이지 수가 바뀌었을 수도 있으니 지금 있는 페이지의 결과만 사용
            v.search_hits = [(p, r) for p, r in self._busy(v.pdf.search, q) if p < len(v.canvases)]
            v.search_rev = v.pdf.revision
            v.search_idx = -1
            for c in v.canvases:
                c.highlights = []
            if not v.search_hits:
                self.statusBar().showMessage(f"'{q}'을(를) 찾을 수 없습니다. (스캔 문서는 먼저 OCR 하세요)", 5000)
                for c in v.canvases:
                    c.update()
                return
            for p, r in v.search_hits:
                v.canvases[p].highlights.append(r)
            for c in v.canvases:
                c.update()
        v.search_idx = (v.search_idx + 1) % len(v.search_hits)
        p, r = v.search_hits[v.search_idx]
        if p != v.cur or not v.continuous:
            v.goto(p)
        QApplication.processEvents()
        v.ensure_visible(p, r)
        self.statusBar().showMessage(f"{v.search_idx + 1} / {len(v.search_hits)}", 3000)

    # ================================================================ OCR / 기타 도구
    def run_ocr(self, all_pages):
        v = self.view
        if not v:
            return
        lang = self.lang_combo.currentText()
        if lang.startswith("("):
            QMessageBox.warning(self, "OCR", "OCR 언어 데이터(tessdata)가 없습니다. 프로그램을 다시 설치해 주세요.")
            return
        self.settings.setValue("ocr_lang", lang)
        pages = list(range(v.pdf.page_count)) if all_pages else [v.cur]
        prog, cb = self._progress("문자인식(OCR) 중…", len(pages))
        texts = []
        try:
            v.pdf.snapshot()
            for i, p in enumerate(pages):
                prog.setLabelText(f"문자인식(OCR) 중… {p + 1} 페이지 ({i + 1}/{len(pages)})")
                if not cb(i, len(pages)):
                    break
                t = v.pdf.ocr_page(p, lang, snapshot=False)
                if t:
                    texts.append(f"── {p + 1} 페이지 ──\n{t}" if all_pages else t)
        except Exception as e:
            prog.close()
            self._error("OCR 실패", e)
            v.rebuild()
            return
        prog.close()
        v.banner.hide()
        v.refresh_pages(pages)
        self._update_enabled()
        if texts:
            TextResultDialog(self, "OCR 결과", "\n\n".join(texts),
                             "인식한 글자를 PDF에 투명 텍스트로 넣었습니다. 이제 검색·복사·편집할 수 있습니다.\n"
                             "[편집] 도구로 초록색으로 표시되는 글자를 클릭하면 수정할 수 있습니다.").exec()
        else:
            QMessageBox.information(self, "OCR", "새로 인식된 글자가 없습니다.\n(이미 텍스트가 있는 부분은 건너뜁니다)")

    def show_page_text(self):
        v = self.view
        TextResultDialog(self, f"{v.cur + 1} 페이지 텍스트", v.pdf.page_text(v.cur)).exec()

    def compare_docs(self):
        v = self.view
        p, _ = QFileDialog.getOpenFileName(self, "비교할 PDF", self.settings.value("last_dir", ""), "PDF (*.pdf)")
        if not p:
            return
        try:
            other = pymupdf.open(p)
            html, n = self._busy(tools.compare, v.pdf.doc, other, v.title.rstrip(" *"), os.path.basename(p))
        except Exception as e:
            self._error("문서 비교 실패", e)
            return
        HtmlDialog(self, f"문서 비교 — 차이 {n}곳", html).exec()

    def help(self):
        QMessageBox.information(self, "사용법", (
            "■ 위쪽 리본 메뉴에서 기능을 고르세요: 홈 · 편집 · 주석 · 페이지 · 변환 · 보안 · 도구 · 보기\n\n"
            "■ 텍스트 수정: [편집] 도구에서 글자를 클릭 → 그 자리에서 바로 수정 (원본 글꼴·크기·색 유지)\n"
            "   서식 도구 모음: 글꼴·크기·굵게·기울임·밑줄·색·정렬 / 상자 밖 클릭·Ctrl+Enter 적용, Esc 취소\n"
            "■ 텍스트 상자 이동: 글자를 누른 채 끌기 (Shift: 가로·세로로만), 편집 중에는 점선 테두리를 끌기\n"
            "■ 텍스트 추가: 빈 곳 더블클릭, 또는 [텍스트 추가] 도구로 클릭(자동 폭)·드래그(폭 지정)\n"
            "■ 복사·붙여넣기: Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+A — 글자, 텍스트 상자(같은 서식), 이미지,\n"
            "   다른 프로그램에서 복사한 글자·그림도 마우스 위치에 붙여넣기\n"
            "■ 텍스트 선택/복사: [텍스트 선택] 도구로 드래그 → Ctrl+C, 우클릭으로 형광펜·밑줄\n"
            "■ 주석: 형광펜·밑줄·취소선(글자 드래그), 메모(클릭), 펜, 사각형, 원, 선, 화살표\n"
            "   주석을 클릭하면 선택 → 이동, Del 삭제, 우클릭으로 색·불투명도·굵기 변경\n"
            "■ 전자 서명/도장: [주석] 탭 → 서명이나 도장을 고른 뒤 넣을 곳 클릭\n"
            "■ 이미지: 클릭해 선택 → 드래그 이동, 모서리로 크기 조절, 우클릭으로 편집\n"
            "■ 페이지: 왼쪽 페이지 목록에서 끌어서 순서 변경, 여러 개 선택 후 회전·삭제\n"
            "■ 합치기·분할·추출·페이지 번호·머리글/바닥글·워터마크: [페이지] 탭\n"
            "■ 변환: PDF → 워드/엑셀/PPT/이미지/텍스트, 이미지·문서(워드·엑셀·PPT·한글) → PDF\n"
            "■ 보안: 암호 설정·해제, 용량 줄이기, 문서 속성\n"
            "■ OCR: 스캔 문서의 글자를 인식해 검색·복사·편집 가능하게\n"
            "■ 책갈피: 왼쪽 [책갈피] 패널 또는 Ctrl+B\n\n"
            "단축키: Ctrl+O 열기, Ctrl+S 저장, Ctrl+P 인쇄, Ctrl+Z 실행 취소, Ctrl+Y·Ctrl+Shift+Z 다시 실행,\n"
            "Ctrl+F 찾기, Ctrl+휠·터치패드 확대/축소(마우스 위치 기준), Ctrl+0 실제 크기, Ctrl+1 폭 맞춤,\n"
            "방향키 선택한 그림·주석 1pt 이동(Shift 10pt), Del 삭제, F11 전체 화면, Ctrl+W 탭 닫기, Esc 취소"))

    def about(self):
        mg = ads.manager()
        rows = []
        for key, label in (("blog", "사용법 블로그"), ("download", "공식 다운로드"), ("source", "소스 코드 (AGPL-3.0)"),
                           ("contact", "문의")):
            u = mg.link(key)
            if u:
                shown = u[7:] if u.startswith("mailto:") else u
                rows.append(f'{label}: <a href="{u}">{shown}</a>')
        QMessageBox.about(self, "정보", f"<b>{APP_NAME}</b> v{__version__}<br>"
                          "무료 프로그램 · 개인·기업 누구나 사용할 수 있습니다.<br><br>"
                          + "<br>".join(rows) + ("<br><br>" if rows else "")
                          + f"PyMuPDF {pymupdf.VersionBind} · Qt(PySide6) · Tesseract OCR · pdf2docx<br>"
                          "이 프로그램은 GNU AGPL-3.0 라이선스로 배포되며 무보증입니다.<br>"
                          "광고 목록과 배너 그림만 내려받으며, 문서·개인 정보는 전송하지 않습니다.")


def QPointF_(*a):
    from PySide6.QtCore import QPointF
    return QPointF(*a)


def QRectF_(x, y, w, h):
    from PySide6.QtCore import QRectF
    return QRectF(x, y, w, h)
