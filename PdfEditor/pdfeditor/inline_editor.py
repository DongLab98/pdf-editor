"""알PDF 방식의 페이지 위 직접 텍스트 편집.

글자를 클릭하면 그 자리에 편집 상자가 열리고(원본 글꼴로 표시), 위에 서식 도구 모음이 뜹니다.
- 글꼴 · 크기 · 굵게 · 기울임 · 밑줄 · 색 · 정렬(왼쪽/가운데/오른쪽/양쪽)
- ✥ 손잡이로 상자 이동, 오른쪽 가장자리 손잡이로 폭(줄바꿈 너비) 조절
- 상자 밖을 클릭하거나 Ctrl+Enter → 적용, Esc → 취소
"""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPalette, QPixmap, QTextBlockFormat,
                           QTextCursor, QTextOption)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QCompleter, QFrame, QHBoxLayout, QTextEdit,
                               QToolButton)

from . import fontmgr, theme
from .dialogs import ColorButton
from .fontmgr import build_chain, find_variant

_qt_families: dict = {}


def qt_family_for(font: pymupdf.Font) -> str | None:
    """PyMuPDF 글꼴을 Qt 에 등록해 같은 모양으로 미리보기."""
    key = id(font)
    if key in _qt_families:
        return _qt_families[key]
    fam = None
    data = fontmgr.font_bytes(font)
    if data:
        fid = QFontDatabase.addApplicationFontFromData(data)
        if fid >= 0:
            fams = QFontDatabase.applicationFontFamilies(fid)
            fam = fams[0] if fams else None
    _qt_families[key] = fam
    return fam


class _Edit(QTextEdit):
    commitRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(3)  # 첫 글자 왼쪽이 잘리지 않게 (상자를 그만큼 바깥으로)
        self.viewport().setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("QTextEdit{background:transparent;border:none}")

    def insertFromMimeData(self, source):
        # 붙여넣기는 서식 없는 글자로
        if source.hasText():
            self.textCursor().insertText(source.text().replace("\r\n", "\n").replace("\r", "\n"))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            e.ignore()  # Ctrl+휠은 문서 확대/축소로
            return
        super().wheelEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelRequested.emit()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.commitRequested.emit()
            return
        super().keyPressEvent(e)


class _DragHandle(QToolButton):
    """누른 채 끌면 delta 를 알려 주는 손잡이."""
    dragged = Signal(QPoint)

    def __init__(self, parent, text, cursor):
        super().__init__(parent)
        self.setText(text)
        self.setCursor(cursor)
        self._last = None

    def mousePressEvent(self, e):
        self._last = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._last is not None:
            p = e.globalPosition().toPoint()
            self.dragged.emit(p - self._last)
            self._last = p

    def mouseReleaseEvent(self, e):
        self._last = None


class SizeBox(QComboBox):
    """글자 크기 입력/선택 (QDoubleSpinBox 와 같은 value/setValue/valueChanged)."""
    valueChanged = Signal(float)

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.addItems(["8", "9", "10", "10.5", "11", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "72"])
        self.setFixedWidth(72)
        self.setToolTip("글자 크기 (pt)")
        self._v = 11.0
        self.currentTextChanged.connect(self._changed)

    def _changed(self, t):
        try:
            v = float(t.replace("pt", "").strip())
        except ValueError:
            return
        if 1 <= v <= 500 and abs(v - self._v) > 1e-6:
            self._v = v
            self.valueChanged.emit(v)

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = float(v)
        self.blockSignals(True)
        self.setCurrentText(f"{self._v:g}")
        self.lineEdit().setCursorPosition(0)   # 좁은 칸에서 "11.5"가 ".5"로 잘려 보이지 않게
        self.blockSignals(False)


class FormatBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("FormatBar{background:#ffffff;border:1px solid #d5dbe5;border-radius:8px}"
                           "QToolButton{min-width:24px;min-height:24px;border:1px solid transparent;border-radius:5px;"
                           "background:transparent}"
                           "QToolButton:checked{background:#e8efff;border-color:#c9d8fb}"
                           "QToolButton:hover{background:#f1f4f9}"
                           "QComboBox,QDoubleSpinBox{min-height:22px}")
        eff = __import__("PySide6.QtWidgets", fromlist=["QGraphicsDropShadowEffect"]).QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(18)
        eff.setOffset(0, 3)
        eff.setColor(QColor(15, 23, 42, 50))
        self.setGraphicsEffect(eff)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(3)
        self.grip = _DragHandle(self, "", Qt.SizeAllCursor)
        self.grip.setIcon(theme.icon("grip", theme.MUTED))
        self.grip.setToolTip("끌어서 텍스트 상자 이동")
        self.font = QComboBox()
        self.font.setEditable(True)
        self.font.setInsertPolicy(QComboBox.NoInsert)
        self.font.setMinimumWidth(170)
        self.font.setMaximumWidth(230)
        self.size = SizeBox()
        self.b = self._tb("", "굵게", icon="bold")
        self.i = self._tb("", "기울임", icon="italic")
        self.u = self._tb("", "밑줄", icon="underline")
        self.color = ColorButton((0, 0, 0), compact=True)
        self.color.setFixedWidth(30)
        self.color.setToolTip("글자색")
        self.align_group = QButtonGroup(self)
        self.align_btns = {}
        for key, ic, tip in (("left", "align-left", "왼쪽 정렬"), ("center", "align-center", "가운데 정렬"),
                             ("right", "align-right", "오른쪽 정렬"), ("justify", "align-justify", "양쪽 정렬")):
            bt = self._tb("", tip, icon=ic)
            self.align_group.addButton(bt)
            self.align_btns[key] = bt
        self.more = QToolButton()
        self.more.setIcon(theme.icon("ellipsis", theme.INK_SOFT))
        self.more.setToolTip("고급 수정 (대화상자)")
        self.ok = QToolButton()
        self.ok.setText("적용")
        self.ok.setIcon(theme.icon("check", "#ffffff"))
        self.ok.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.ok.setToolTip("적용 (Ctrl+Enter, 또는 상자 밖 클릭)")
        self.ok.setStyleSheet("QToolButton{background:#2563eb;color:white;font-weight:600;padding:2px 10px;"
                              "border-radius:5px} QToolButton:hover{background:#1d4ed8}")
        self.cancel = QToolButton()
        self.cancel.setIcon(theme.icon("x", theme.INK_SOFT))
        self.cancel.setToolTip("취소 (Esc)")
        for w in (self.grip, self.font, self.size, self.b, self.i, self.u, self.color, *self.align_btns.values(),
                  self.more, self.ok, self.cancel):
            lay.addWidget(w)
        self.adjustSize()

    def _tb(self, text, tip, bold=False, italic=False, underline=False, icon=None):
        bt = QToolButton()
        bt.setText(text)
        if icon:
            bt.setIcon(theme.icon(icon, theme.INK))
        bt.setToolTip(tip)
        bt.setCheckable(True)
        f = bt.font()
        f.setBold(bold)
        f.setItalic(italic)
        f.setUnderline(underline)
        bt.setFont(f)
        return bt


class InlineTextSession(QObject):
    """한 번의 페이지 위 텍스트 편집. finished(applied: bool) 를 내보냄."""
    finished = Signal(bool)

    def __init__(self, main, view, canvas, item=None, point: pymupdf.Point | None = None, initial_text=None,
                 style_item=None, wrap_width: float | None = None):
        super().__init__(canvas)
        self.main, self.view, self.canvas = main, view, canvas
        self.pdf = view.pdf
        self.pno = canvas.pno
        self.item = item
        self.src = item or style_item  # 서식을 가져올 원본
        self.done = False
        z = canvas.zoom
        src = self.src
        self.orig_bold = bool(src and src.bold and not src.invisible)
        self.orig_italic = bool(src and src.italic and not src.invisible)
        self.size0 = (max(4.0, item.bbox.height / max(1, len(item.lines)) * 0.76) if item and item.invisible
                      else (src.size if src else 11.0))
        self.fill = None
        color = src.rgb if src else (0, 0, 0)
        if item and (item.invisible or item.on_image):
            self.fill, fg = self.pdf.sample_colors(self.pno, item.bbox)
            if item.invisible:
                color = fg
        self.pitch0 = item.pitch if item and item.is_para else (src.pitch if src and src.is_para else self.size0 * 1.25)
        self.align0 = item.align if item else "left"
        self.wrap = bool(item and item.is_para)

        canvas.show_boxes = False  # 편집 중에는 다른 상자 테두리 숨김
        # ---- 배경: 원래 글자를 지운 페이지 미리보기
        if item is not None:
            self._set_background()

        # ---- 편집 상자
        self.edit = _Edit(canvas)
        if item is None:
            self.edit.setPlaceholderText("텍스트 입력")
        canvas.frame_mover = self._move_by
        self.edit.commitRequested.connect(self.commit)
        self.edit.cancelRequested.connect(self.cancel)
        self.bar = FormatBar(canvas)
        self.wgrip = _DragHandle(canvas, "", Qt.SizeHorCursor)
        self.wgrip.setFixedSize(8, 18)
        self.wgrip.setStyleSheet("QToolButton{background:#1f6fff;border:1px solid white;border-radius:2px}")
        self.wgrip.setToolTip("끌어서 줄바꿈 너비 조절")

        # 위치/크기
        if item is not None:
            r = canvas.to_view(item.bbox)
            # 첫 줄 기준선이 원래 위치에 오도록
            base_view = canvas.to_view(pymupdf.Rect(item.origin, item.origin)).topLeft()
            self.anchor = QPointF(r.x() if item.is_para else base_view.x(), base_view.y())
            self.box_w = max(r.width(), 20)
        else:
            pv = canvas.to_view(pymupdf.Rect(point, point)).topLeft()
            self.anchor = None  # 새 텍스트: 클릭 위치가 상자 왼쪽 위
            self.click_view = pv
            self.box_w = (wrap_width * z) if wrap_width else 260 * z / 1.25
            if wrap_width:
                self.wrap = True
        self.moved = QPointF(0, 0)

        # 도구 모음 초기값
        b = self.bar
        b.font.addItem(self._orig_label(), ("orig", None))
        seen = set()
        for it in self.pdf.text_items(self.pno, False):
            if it.invisible or it.font in seen:
                continue
            seen.add(it.font)
            b.font.addItem(f"문서: {fontmgr.decode_pdf_name(it.font)}", ("doc", it))
        for name, sf in fontmgr.SYSTEM_FONTS.display_list():
            b.font.addItem(name, ("sys", sf))
        comp = QCompleter([b.font.itemText(i) for i in range(b.font.count())], b.font)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        b.font.setCompleter(comp)
        b.size.setValue(round(self.size0, 1))
        b.b.setChecked(self.orig_bold)
        b.i.setChecked(self.orig_italic)
        b.color.set_color(color)
        b.align_btns[self.align0].setChecked(True)
        self.init_state = self._state()

        b.font.currentIndexChanged.connect(self._restyle)
        b.size.valueChanged.connect(self._restyle)
        for bt in (b.b, b.i, b.u):
            bt.toggled.connect(self._restyle)
        b.color.on_change = self._restyle
        b.align_group.buttonClicked.connect(lambda *_: self._restyle())
        b.grip.dragged.connect(self._move_by)
        self.wgrip.dragged.connect(self._resize_by)
        b.ok.clicked.connect(self.commit)
        b.cancel.clicked.connect(self.cancel)
        b.more.clicked.connect(self._advanced)
        self.edit.textChanged.connect(lambda: QTimer.singleShot(0, self._relayout))

        text = item.text if item is not None else (initial_text or "")
        self.edit.setPlainText(text)
        self._restyle()
        for w in (self.edit, self.bar, self.wgrip):
            w.show()
            w.raise_()
        self.edit.setFocus()
        cur = self.edit.textCursor()
        cur.movePosition(QTextCursor.End)
        self.edit.setTextCursor(cur)
        canvas.installEventFilter(self)
        QTimer.singleShot(0, self._ensure_visible)

    # ------------------------------------------------------------------ 상태
    def _orig_label(self):
        if self.item is not None and self.item.invisible:
            return "스캔 문서용 글꼴"
        if self.src is None:
            return "기본 글꼴 (맑은 고딕)"
        prefix = "원본" if self.item is not None else ("복사한 서식" if self.main.text_clip and
                                                    self.main.text_clip[1] is self.src else "주변")
        return f"{prefix}: {fontmgr.decode_pdf_name(self.src.font)}"

    def _state(self):
        b = self.bar
        return (b.font.currentIndex(), round(b.size.value(), 1), b.b.isChecked(), b.i.isChecked(), b.u.isChecked(),
                tuple(round(v, 3) for v in b.color.rgb), self._align())

    def _align(self):
        for k, bt in self.bar.align_btns.items():
            if bt.isChecked():
                return k
        return "left"

    def resolve_chain(self):
        """(chain, synth_bold, synth_italic)"""
        b = self.bar
        bold, italic = b.b.isChecked(), b.i.isChecked()
        data = b.font.currentData()
        if data is None:
            idx = b.font.findText(b.font.currentText(), Qt.MatchContains)
            data = b.font.itemData(idx) if idx >= 0 else ("orig", None)
        kind, obj = data
        flags = 16 if bold else 0
        if kind in ("orig", "doc"):
            src = self.src if kind == "orig" else obj
            if src is None or (src.invisible and kind == "orig"):
                sf = find_variant("Malgun Gothic", bold, italic) or find_variant("NanumGothic", bold, italic)
                if sf:
                    return build_chain("", flags, None, override=sf), False, False
                return build_chain("", flags, None), False, italic
            ob, oi = (self.orig_bold, self.orig_italic) if kind == "orig" else (src.bold, src.italic)
            base = self.pdf.chain_for(src)
            if bold == ob and italic == oi:
                return base, False, False
            names = [src.font] + [ln.sysfont.full for ln in base.links[:1] if ln.sysfont]
            for nm in names:
                sf = find_variant(nm, bold, italic)
                if sf:
                    return build_chain("", flags, None, override=sf), False, False
            if (bold or not ob) and (italic or not oi):
                return base, bold and not ob, italic and not oi
            return build_chain("", flags, None), bold and False, italic and not oi
        sf = obj
        v = sf if (sf.bold == bold and sf.italic == italic) else find_variant(sf.full, bold, italic)
        if v:
            return build_chain("", flags, None, override=v), False, False
        return build_chain("", flags, None, override=sf), bold and not sf.bold, italic and not sf.italic

    # ------------------------------------------------------------------ 표시
    def _set_background(self):
        """원래 글자를 지운 페이지를 캔버스 배경으로 (편집 중 겹쳐 보이지 않게)."""
        try:
            tmp = pymupdf.open()
            tmp.insert_pdf(self.pdf.doc, from_page=self.pno, to_page=self.pno)
            page = tmp[0]
            rects = [ln[0] for ln in self.item.lines] or [self.item.bbox]
            for r in rects:
                h = r.height
                page.add_redact_annot(pymupdf.Rect(r.x0 + 0.2, r.y0 + h * 0.25, r.x1 - 0.2, r.y1 - h * 0.25),
                                      fill=False, cross_out=False)
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
            if self.fill is not None:
                for r in rects:
                    page.draw_rect(r + (-2, -1.5, 2, 1.5), color=None, fill=self.fill, overlay=True)
            c = self.canvas
            dpr = c.devicePixelRatioF()
            pm = page.get_pixmap(matrix=pymupdf.Matrix(c.zoom * dpr, c.zoom * dpr), alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            pix = QPixmap.fromImage(img)
            pix.setDevicePixelRatio(dpr)
            c.pix = pix
            c.update()
        except Exception:
            pass

    def _restyle(self, *_):
        chain, sb, si = self.resolve_chain()
        self.chain, self.synth_b, self.synth_i = chain, sb, si
        b = self.bar
        size = b.size.value()
        z = self.canvas.zoom
        fams = []
        for ln in chain.links[:2]:
            f = qt_family_for(ln.font)
            if f:
                fams.append(f)
        fams += ["Malgun Gothic", "맑은 고딕", "NanumGothic", "Noto Sans CJK KR"]
        qf = QFont()
        qf.setFamilies(fams)
        qf.setPixelSize(max(1, round(size * z)))
        qf.setBold(sb)
        qf.setItalic(si)
        qf.setUnderline(b.u.isChecked())
        qf.setHintingPreference(QFont.PreferNoHinting)
        self.qfont = qf
        e = self.edit
        e.setFont(qf)
        e.document().setDefaultFont(qf)
        pal = e.palette()
        pal.setColor(QPalette.Text, QColor.fromRgbF(*b.color.rgb))
        pal.setColor(QPalette.Base, QColor(0, 0, 0, 0))
        e.setPalette(pal)
        align = self._align()
        qa = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight,
              "justify": Qt.AlignJustify}[align]
        pitch_px = (self.pitch0 * size / self.size0 if self.size0 else size * 1.25) * z
        self.pitch_px = pitch_px
        cur = QTextCursor(e.document())
        cur.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setAlignment(qa)
        fmt.setLineHeight(pitch_px, 2)  # 2 = FixedHeight
        cur.mergeBlockFormat(fmt)
        cf = cur.charFormat()
        cf.setFont(qf)
        cur.mergeCharFormat(cf)
        if align != "left" and not self.wrap:
            self.wrap = True  # 정렬은 상자 폭 기준이므로 줄바꿈 모드로
        self._relayout()

    def _relayout(self):
        if not hasattr(self, "qfont") or self.done:
            return
        e = self.edit
        fm = QFontMetricsF(self.qfont)
        doc = e.document()
        if self.wrap:
            e.setLineWrapMode(QTextEdit.FixedPixelWidth)
            e.setLineWrapColumnOrWidth(int(self.box_w) + 6)
            e.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            w = self.box_w
        else:
            e.setLineWrapMode(QTextEdit.NoWrap)
            doc.setTextWidth(-1)
            w = max(doc.idealWidth() - 6, fm.horizontalAdvance("가") * 2)
        doc.setTextWidth(w)
        doc.setTextWidth(w + 6)
        h = max(self.pitch_px, doc.size().height() - 6)
        ascent = fm.ascent()
        # Qt 고정 줄높이에서 첫 기준선 ≈ 줄높이 - 하강 높이
        base_in_line = max(ascent, self.pitch_px - fm.descent())
        if self.anchor is not None:
            x = self.anchor.x() + self.moved.x()
            y = self.anchor.y() - base_in_line + self.moved.y()
        else:
            x = self.click_view.x() + self.moved.x()
            y = self.click_view.y() + self.moved.y()
        self.base_in_line = base_in_line
        # 테두리·안쪽 여백만큼 키우고 왼쪽/위로 당겨서, 글자가 원래 자리에 정확히 겹치고 잘리지 않게 함
        vg = e.viewport().geometry()
        left, top = vg.x(), vg.y()
        cw = max(0, e.width() - vg.width()) if e.width() > 0 else 2 * left
        ch = max(0, e.height() - vg.height()) if e.height() > 0 else 2 * top
        e.setGeometry(QRect(int(x) - 3 - left, int(y) - 3 - top, int(w) + 6 + cw + 3, int(h) + 6 + ch))
        self.canvas.edit_frame = e.geometry()
        self.canvas.update()
        self._place_bar()

    def _place_bar(self):
        e, bar = self.edit, self.bar
        bar.adjustSize()
        g = e.geometry()
        by = g.y() - bar.height() - 6
        if by < 0:
            by = g.bottom() + 6
        bx = min(max(0, g.x()), max(0, self.canvas.width() - bar.width()))
        bar.move(bx, by)
        self.wgrip.move(g.right() - 3, g.y() + g.height() // 2 - 9)

    def _ensure_visible(self):
        sc = self.view.scroll
        g = self.edit.geometry().united(self.bar.geometry())
        c = self.canvas
        sc.ensureVisible(c.x() + g.center().x(), c.y() + g.center().y(), g.width() // 2 + 20, g.height() // 2 + 20)

    def _move_by(self, d: QPoint):
        self.moved += QPointF(d)
        self._relayout()

    def _resize_by(self, d: QPoint):
        self.wrap = True
        self.box_w = max(20, self.box_w + d.x())
        self._relayout()

    def eventFilter(self, obj, ev):
        if obj is self.canvas and ev.type() == QEvent.Resize and not self.done:
            QTimer.singleShot(0, self._relayout)
        return False

    # ------------------------------------------------------------------ 결과
    def _layout_lines(self):
        """Qt 가 실제로 줄바꿈한 대로 줄 목록 (화면에 보이는 그대로 저장)."""
        doc = self.edit.document()
        out = []
        for i in range(doc.blockCount()):
            blk = doc.findBlockByNumber(i)
            t = blk.text()
            lay = blk.layout()
            if lay.lineCount() == 0:
                out.append("")
                continue
            for li in range(lay.lineCount()):
                ln = lay.lineAt(li)
                out.append(t[ln.textStart(): ln.textStart() + ln.textLength()].rstrip())
        while len(out) > 1 and out[-1] == "" and self.edit.toPlainText().endswith("\n") is False:
            out.pop()
        return out

    def commit(self):
        if self.done:
            return
        text = self.edit.toPlainText()
        unchanged = (self.item is not None and text == self.item.text and self._state() == self.init_state
                     and self.moved.manhattanLength() < 1)
        if unchanged or (self.item is None and not text.strip()):
            self._close(False)
            return
        c = self.canvas
        z = c.zoom
        b = self.bar
        size = b.size.value()
        pitch = self.pitch_px / z
        align = self._align()
        lines = self._layout_lines()
        box_w = self.box_w / z
        indent0 = 0.0
        if self.item is not None:
            it = self.item
            if it.is_para:
                min_x = min(ln[1].x for ln in it.lines)
                origin = pymupdf.Point(min_x, it.origin.y)
                if align in ("left", "justify"):
                    indent0 = it.lines[0][1].x - min_x
                if align in ("center", "right"):
                    origin = pymupdf.Point(it.bbox.x0, it.origin.y)
            else:
                origin = pymupdf.Point(it.origin)
                if align in ("center", "right"):
                    origin = pymupdf.Point(it.bbox.x0, it.origin.y) if it.direction == (1.0, 0.0) else origin
            direction = it.direction
            if self.moved.manhattanLength() >= 1:
                a = c.to_pdf(QPointF(0, 0))
                d = c.to_pdf(self.moved) - a
                origin = origin + d
        else:
            top_left = QPointF(self.click_view.x() + self.moved.x(), self.click_view.y() + self.moved.y())
            origin = c.to_pdf(QPointF(top_left.x(), top_left.y() + self.base_in_line))
            p0 = c.to_pdf(QPointF(0, 0))
            p1 = c.to_pdf(QPointF(1, 0))
            dv = p1 - p0
            ln = (dv.x ** 2 + dv.y ** 2) ** 0.5 or 1
            direction = (round(dv.x / ln, 6), round(dv.y / ln, 6))
        chain, sb, si = self.chain, self.synth_b, self.synth_i
        item, fill, color, ul = self.item, self.fill, b.color.rgb, b.u.isChecked()
        self._close(True)
        # view=self.view: 탭을 바꾸는 순간 적용돼도 편집한 문서의 탭을 다시 그림
        res = self.main._do(self.pno, lambda: self.pdf.write_paragraph(
            self.pno, item, lines, origin=origin, box_width=box_w, chain=chain, size=size, color=color, pitch=pitch,
            align=align, direction=direction, synth_bold=sb, synth_italic=si, underline=ul, fill=fill,
            first_indent=indent0), "텍스트 수정" if item is not None else "텍스트 추가", view=self.view)
        if res is not None:
            self.main.statusBar().showMessage(f"사용 글꼴: {res.chain_desc}", 6000)
        else:
            # 쓰기에 실패하면 문서는 되돌려지고, 입력한 글자는 잃지 않도록 클립보드에 남김
            QApplication.clipboard().setText(text)
            self.main.statusBar().showMessage("적용하지 못했습니다. 입력한 글자는 클립보드에 복사했습니다.", 10000)

    def cancel(self):
        self._close(False)
        self.canvas.render()

    def _advanced(self):
        item = self.item
        self._close(False)
        self.canvas.render()
        if item is not None:
            self.main.edit_text_dialog(self.canvas, item)

    def _close(self, applied):
        if self.done:
            return
        self.done = True
        self.canvas.show_boxes = True
        self.canvas.edit_frame = None
        self.canvas.frame_mover = None
        self.canvas.update()
        self.canvas.removeEventFilter(self)
        for w in (self.edit, self.bar, self.wgrip):
            w.hide()
            w.deleteLater()
        self.finished.emit(applied)
