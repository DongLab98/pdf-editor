"""페이지 한 장을 표시하고 마우스 조작을 처리하는 위젯 (연속 보기에서는 페이지마다 하나씩)."""
from __future__ import annotations

import math

import pymupdf
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from .annots import AnnotItem, WidgetItem
from .engine import ImageItem, PdfDocument, TextItem

(TOOL_SELECT, TOOL_ADD_TEXT, TOOL_ADD_IMAGE, TOOL_ERASE, TOOL_HAND, TOOL_SELECT_TEXT, TOOL_HIGHLIGHT,
 TOOL_UNDERLINE, TOOL_STRIKE, TOOL_NOTE, TOOL_PEN, TOOL_RECT, TOOL_ELLIPSE, TOOL_LINE, TOOL_ARROW,
 TOOL_LINK, TOOL_PLACE) = range(17)
MARKUP_TOOLS = {TOOL_HIGHLIGHT: "highlight", TOOL_UNDERLINE: "underline", TOOL_STRIKE: "strikeout"}
SHAPE_TOOLS = {TOOL_RECT: "rect", TOOL_ELLIPSE: "ellipse", TOOL_LINE: "line", TOOL_ARROW: "arrow"}
RUBBER_TOOLS = {TOOL_ADD_IMAGE, TOOL_ERASE, TOOL_LINK}
HANDLE = 7


class PageCanvas(QWidget):
    textClicked = Signal(object)
    textContext = Signal(object, object)
    imageContext = Signal(object, object)
    imageMoved = Signal(object, object)
    imageDoubleClicked = Signal(object)
    annotContext = Signal(object, object)
    annotMoved = Signal(object, object)
    annotDoubleClicked = Signal(object)
    widgetClicked = Signal(object)
    linkClicked = Signal(dict)
    addTextAt = Signal(object)
    addTextBox = Signal(object, float)      # 왼쪽 위 점, 폭(pt) — 드래그로 만든 텍스트 상자
    textMoved = Signal(object, object)      # TextItem, 이동량(pymupdf.Point)
    rectDrawn = Signal(int, object)
    markupDrawn = Signal(str, list, str)
    textSelected = Signal(list, str)
    selectionContext = Signal(object)
    noteAt = Signal(object)
    inkDrawn = Signal(list)
    shapeDrawn = Signal(str, object, object)
    placeAt = Signal(object)
    hoverInfo = Signal(str)
    emptyContext = Signal(object, object)   # pymupdf.Point, QPoint(global)
    focused = Signal()
    panBy = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.pdf: PdfDocument | None = None
        self.pno = 0
        self.zoom = 1.0
        self.pix: QPixmap | None = None
        self.tool = TOOL_SELECT
        self.line_mode = False
        self.para_mode = True
        self.show_boxes = True
        self.before_press = None   # 편집 중인 상자 확정용 콜백
        self.edit_frame = None     # 편집 중인 상자 테두리 (QRect)
        self.frame_mover = None    # 편집 중 상자 테두리를 끌 때 호출 (QPoint 이동량)
        self.pix_zoom = None       # pix 를 렌더링한 배율 (확대 중에는 이전 그림을 늘려 보여 줌)
        self.hover = None
        self.sel_image: ImageItem | None = None
        self.sel_annot: AnnotItem | None = None
        self.highlights: list[pymupdf.Rect] = []
        self.text_sel: list[pymupdf.Rect] = []
        self.text_sel_str = ""
        self.place_size: tuple | None = None   # (w, h) pt, 서명/도장 배치용
        self.pen_color = QColor(220, 30, 30)
        self.pen_width = 2.0
        self._drag = None
        self._preview: QRectF | None = None
        self._stroke: list[QPointF] = []
        self.select_after: pymupdf.Rect | None = None

    # ---------------------------------------------------------------- 설정/렌더링
    def setup(self, pdf: PdfDocument, pno: int, zoom: float):
        self.pdf, self.pno, self.zoom = pdf, pno, zoom
        r = pdf.page(pno).rect
        self.setFixedSize(max(1, int(r.width * zoom)), max(1, int(r.height * zoom)))
        if self.pix is not None and self.pix_zoom is not None and self.pix_zoom != zoom and getattr(self, "_same_page", False):
            pass  # 확대/축소만 바뀜: 이전 그림을 늘려 보여 주고 나중에 다시 렌더링
        else:
            self.pix = None
        self._same_page = False
        self.hover = None
        self.update()

    def rezoom(self, zoom: float):
        """페이지 내용은 그대로, 배율만 바꿈 (깜빡임 없이)."""
        self._same_page = True
        self.setup(self.pdf, self.pno, zoom)

    @property
    def stale(self):
        return self.pix is None or self.pix_zoom != self.zoom

    def set_page(self, pdf: PdfDocument, pno: int, zoom: float):
        """설정 + 즉시 렌더링 (선택 유지)."""
        self.setup(pdf, pno, zoom)
        self._restore_selection()
        self.render()

    def _restore_selection(self):
        target = self.select_after or (self.sel_image.bbox if self.sel_image is not None else None)
        self.select_after = None
        self.sel_image = None
        if target is not None:
            for im in self.pdf.image_items(self.pno):
                if abs(im.bbox.x0 - target.x0) < 1.5 and abs(im.bbox.y0 - target.y0) < 1.5:
                    self.sel_image = im
        if self.sel_annot is not None:
            xref = self.sel_annot.xref
            self.sel_annot = next((a for a in self.pdf.annot_items(self.pno) if a.xref == xref), None)

    def render(self):
        if not self.pdf or not self.pdf.doc or self.pno >= self.pdf.page_count:
            return
        page = self.pdf.page(self.pno)
        dpr = self.devicePixelRatioF()
        m = pymupdf.Matrix(self.zoom * dpr, self.zoom * dpr)
        pm = page.get_pixmap(matrix=m, alpha=False, annots=True)
        img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
        self.pix = QPixmap.fromImage(img)
        self.pix.setDevicePixelRatio(dpr)
        self.pix_zoom = self.zoom
        self.update()

    def drop(self):
        self.pix = None
        self.pix_zoom = None

    # ---------------------------------------------------------------- 좌표
    def _page(self):
        return self.pdf.page(self.pno)

    def to_pdf(self, p: QPointF) -> pymupdf.Point:
        return pymupdf.Point(p.x() / self.zoom, p.y() / self.zoom) * self._page().derotation_matrix

    def rect_to_pdf(self, r: QRectF) -> pymupdf.Rect:
        return pymupdf.Rect(self.to_pdf(r.topLeft()), self.to_pdf(r.bottomRight())).normalize()

    def to_view(self, r: pymupdf.Rect) -> QRectF:
        rr = pymupdf.Rect(r) * self._page().rotation_matrix
        rr.normalize()
        return QRectF(rr.x0 * self.zoom, rr.y0 * self.zoom, rr.width * self.zoom, rr.height * self.zoom)

    # ---------------------------------------------------------------- 히트 테스트
    def text_at(self, pt):
        cands = [it for it in self.pdf.text_items(self.pno, self.line_mode, self.para_mode)
                 if not it.hidden and (it.bbox + (-1, -1, 1, 1)).contains(pt)]
        return min(cands, key=lambda it: it.bbox.get_area()) if cands else None

    def image_at(self, pt):
        for im in reversed(self.pdf.image_items(self.pno)):
            if im.bbox.contains(pt):
                return im
        return None

    def annot_at(self, pt):
        best = None
        for a in self.pdf.annot_items(self.pno):
            if (a.bbox + (-2, -2, 2, 2)).contains(pt):
                if best is None or a.bbox.get_area() < best.bbox.get_area():
                    best = a
        return best

    def widget_at(self, pt) -> WidgetItem | None:
        for w in self.pdf.widget_items(self.pno):
            if w.bbox.contains(pt):
                return w
        return None

    def link_at(self, pt):
        for ln in self.pdf.links(self.pno):
            if pymupdf.Rect(ln["from"]).contains(pt):
                return ln
        return None

    def _handle_at(self, p: QPointF, bbox):
        r = self.to_view(bbox)
        for k, c in {"tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(), "br": r.bottomRight()}.items():
            if abs(c.x() - p.x()) <= HANDLE + 2 and abs(c.y() - p.y()) <= HANDLE + 2:
                return k
        return None

    # ---------------------------------------------------------------- 그리기
    def paintEvent(self, _ev):
        qp = QPainter(self)
        qp.fillRect(self.rect(), QColor("#ffffff"))
        if self.pix:
            if self.pix_zoom is not None and self.pix_zoom != self.zoom:
                qp.setRenderHint(QPainter.SmoothPixmapTransform)
                qp.drawPixmap(self.rect(), self.pix)
            else:
                qp.drawPixmap(0, 0, self.pix)
        elif self.pdf:
            qp.setPen(QColor("#999"))
            qp.drawText(self.rect(), Qt.AlignCenter, f"{self.pno + 1}")
        qp.setRenderHint(QPainter.Antialiasing)
        for h in self.highlights:
            qp.fillRect(self.to_view(h), QColor(255, 220, 0, 90))
        if self.tool == TOOL_SELECT and self.show_boxes and self.pdf and self.pix is not None:
            pen = QPen(QColor(90, 140, 230, 95), 1, Qt.CustomDashLine)
            pen.setDashPattern([3, 3])
            qp.setPen(pen)
            qp.setBrush(Qt.NoBrush)
            for it in self.pdf.text_items(self.pno, self.line_mode, self.para_mode):
                if it.boxed:
                    qp.drawRect(self.to_view(it.bbox).adjusted(-1, -1, 1, 1))
        if self._drag and self._drag[0] == "textmove" and self._preview is not None:
            src, ghost = self._drag[2][1], self._drag[2][2]
            qp.fillRect(src, QColor(255, 255, 255, 170))
            if ghost is not None:
                qp.setOpacity(0.85)
                qp.drawPixmap(self._preview.topLeft(), ghost)
                qp.setOpacity(1.0)
            pen = QPen(QColor(31, 111, 255), 1.2, Qt.DashLine)
            qp.setPen(pen)
            qp.setBrush(Qt.NoBrush)
            qp.drawRect(self._preview.adjusted(-2, -2, 2, 2))
        for r in self.text_sel:
            qp.fillRect(self.to_view(r), QColor(40, 120, 255, 70))
        if self.hover is not None and self._drag is None:
            r = self.to_view(self.hover.bbox).adjusted(-2, -2, 2, 2)
            if isinstance(self.hover, TextItem):
                col = QColor(30, 120, 255) if not self.hover.invisible else QColor(0, 170, 120)
                qp.setPen(QPen(col, 1.4))
                qp.fillRect(r, QColor(col.red(), col.green(), col.blue(), 30))
            elif isinstance(self.hover, AnnotItem):
                qp.setPen(QPen(QColor(160, 60, 220), 1.4, Qt.DashLine))
            elif isinstance(self.hover, WidgetItem):
                qp.setPen(QPen(QColor(0, 150, 200), 1.6))
                qp.fillRect(r, QColor(0, 150, 200, 30))
            else:
                qp.setPen(QPen(QColor(255, 140, 0), 1.4, Qt.DashLine))
            qp.drawRect(r)
        for sel, col in ((self.sel_image, QColor(255, 120, 0)), (self.sel_annot, QColor(160, 60, 220))):
            if sel is None:
                continue
            r = self._preview if (self._preview is not None and self._drag and self._drag[0] in ("move", "resize")) \
                else self.to_view(sel.bbox)
            qp.setPen(QPen(col, 1.6))
            qp.setBrush(Qt.NoBrush)
            qp.drawRect(r)
            if sel is self.sel_image or getattr(sel, "movable", False):
                qp.setBrush(QColor(255, 255, 255))
                for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                    qp.drawRect(QRectF(c.x() - HANDLE / 2, c.y() - HANDLE / 2, HANDLE, HANDLE))
        if self._drag and self._drag[0] == "addtext" and self._preview is not None and self._preview.width() > 6:
            pen = QPen(QColor(31, 111, 255), 1.2, Qt.DashLine)
            qp.setPen(pen)
            qp.setBrush(QColor(31, 111, 255, 25))
            r = QRectF(self._preview.x(), self._preview.y(), self._preview.width(), 18 * self.zoom)
            qp.drawRect(r)
        if self.edit_frame is not None:
            qp.setBrush(QColor(255, 255, 255, 40))
            qp.setPen(QPen(QColor(31, 111, 255), 1.2, Qt.DashLine))
            qp.drawRect(QRectF(self.edit_frame).adjusted(-2, -2, 2, 2))
        if self._drag and self._drag[0] == "rubber" and self._preview is not None:
            col = QColor(220, 40, 40) if self.tool == TOOL_ERASE else QColor(30, 120, 255)
            qp.setPen(QPen(col, 1.4, Qt.DashLine))
            qp.setBrush(QColor(col.red(), col.green(), col.blue(), 35))
            qp.drawRect(self._preview)
        if self._drag and self._drag[0] == "shape" and self._preview is not None:
            self._paint_shape(qp)
        if self._stroke:
            qp.setPen(QPen(self.pen_color, self.pen_width * self.zoom, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(self._stroke[0])
            for p in self._stroke[1:]:
                path.lineTo(p)
            qp.setBrush(Qt.NoBrush)
            qp.drawPath(path)
        if self.tool == TOOL_PLACE and self.place_size and self.underMouse():
            c = QPointF(self.mapFromGlobal(QCursor.pos()))
            w, h = self.place_size[0] * self.zoom, self.place_size[1] * self.zoom
            qp.setPen(QPen(QColor(30, 120, 255), 1.4, Qt.DashLine))
            qp.setBrush(QColor(30, 120, 255, 30))
            qp.drawRect(QRectF(c.x() - w / 2, c.y() - h / 2, w, h))
        qp.end()

    def _paint_shape(self, qp):
        _k, start, kind = self._drag
        end = self._drag_end
        qp.setPen(QPen(self.pen_color, self.pen_width * self.zoom))
        qp.setBrush(Qt.NoBrush)
        if kind == "rect":
            qp.drawRect(QRectF(start, end).normalized())
        elif kind == "ellipse":
            qp.drawEllipse(QRectF(start, end).normalized())
        else:
            qp.drawLine(start, end)
            if kind == "arrow":
                ang = math.atan2(end.y() - start.y(), end.x() - start.x())
                L = 10 + self.pen_width * self.zoom * 2
                p1 = end - QPointF(L * math.cos(ang - 0.4), L * math.sin(ang - 0.4))
                p2 = end - QPointF(L * math.cos(ang + 0.4), L * math.sin(ang + 0.4))
                qp.setBrush(self.pen_color)
                qp.drawPolygon(QPolygonF([end, p1, p2]))

    # ---------------------------------------------------------------- 마우스
    def _cursor_for_tool(self):
        return {TOOL_HAND: Qt.OpenHandCursor, TOOL_ADD_TEXT: Qt.IBeamCursor, TOOL_SELECT_TEXT: Qt.IBeamCursor,
                TOOL_HIGHLIGHT: Qt.IBeamCursor, TOOL_UNDERLINE: Qt.IBeamCursor, TOOL_STRIKE: Qt.IBeamCursor,
                TOOL_NOTE: Qt.PointingHandCursor, TOOL_PLACE: Qt.BlankCursor if False else Qt.CrossCursor}.get(
            self.tool, Qt.CrossCursor)

    def mouseMoveEvent(self, ev):
        p = ev.position()
        if self._drag:
            kind, start, extra = self._drag
            if kind == "rubber":
                self._preview = QRectF(start, p).normalized()
            elif kind == "move":
                self._preview = extra.translated(p - start)
            elif kind == "resize":
                corner, r0 = extra
                self._preview = self._resized(r0, corner, p, not (ev.modifiers() & Qt.ShiftModifier))
            elif kind == "shape":
                self._drag_end = p
                if ev.modifiers() & Qt.ShiftModifier and extra in ("line", "arrow"):
                    d = p - start
                    if abs(d.x()) > abs(d.y()):
                        self._drag_end = QPointF(p.x(), start.y())
                    else:
                        self._drag_end = QPointF(start.x(), p.y())
                self._preview = QRectF(start, p)
            elif kind == "text":
                self.text_sel, self.text_sel_str = self.pdf.select_words(self.pno, self.to_pdf(start), self.to_pdf(p))
            elif kind == "pen":
                self._stroke.append(p)
            elif kind == "pan":
                self.panBy.emit(ev.globalPosition() - extra)
                self._drag = ("pan", start, ev.globalPosition())
            elif kind == "framemove":
                gp = ev.globalPosition().toPoint()
                if self.frame_mover:
                    self.frame_mover(gp - extra)
                self._drag = ("framemove", start, gp)
            elif kind == "textpress":
                if (p - start).manhattanLength() > 5:
                    item = extra
                    src = self.to_view(item.bbox).adjusted(-1, -1, 1, 1)
                    ghost = None
                    if self.pix is not None:
                        dpr = self.pix.devicePixelRatio()
                        if self.pix_zoom == self.zoom:
                            ghost = self.pix.copy(int(src.x() * dpr), int(src.y() * dpr),
                                                  int(src.width() * dpr), int(src.height() * dpr))
                            ghost.setDevicePixelRatio(dpr)
                    self._drag = ("textmove", start, (item, src, ghost))
                    self.hover = None
                    self.setCursor(Qt.ClosedHandCursor)
            if self._drag and self._drag[0] == "textmove":
                _k, st, (item, src, _g) = self._drag
                d = p - st
                if ev.modifiers() & Qt.ShiftModifier:  # Shift: 가로/세로로만
                    d = QPointF(d.x(), 0) if abs(d.x()) > abs(d.y()) else QPointF(0, d.y())
                self._preview = src.translated(d)
            elif kind == "addtext":
                self._preview = QRectF(start, QPointF(p.x(), start.y() + 4)).normalized()
            self.update()
            return
        if not self.pdf or not self.pdf.doc:
            return
        if self._near_frame(p):
            self.setCursor(Qt.SizeAllCursor)
            self.hoverInfo.emit("끌어서 텍스트 상자 이동")
            return
        pt = self.to_pdf(p)
        new_hover = None
        info = ""
        if self.tool == TOOL_SELECT:
            sel = self.sel_image or (self.sel_annot if self.sel_annot and self.sel_annot.movable else None)
            h = self._handle_at(p, sel.bbox) if sel else None
            if h:
                self.setCursor(Qt.SizeFDiagCursor if h in ("tl", "br") else Qt.SizeBDiagCursor)
            elif sel and sel.bbox.contains(pt):
                self.setCursor(Qt.SizeAllCursor)
            else:
                new_hover = self.widget_at(pt) or self.annot_at(pt) or self.text_at(pt) or self.image_at(pt)
                self.setCursor(Qt.IBeamCursor if isinstance(new_hover, TextItem) else
                               Qt.PointingHandCursor if new_hover else Qt.ArrowCursor)
        elif self.tool == TOOL_HAND:
            ln = self.link_at(pt)
            w = self.widget_at(pt)
            new_hover = w
            self.setCursor(Qt.PointingHandCursor if (ln or w) else Qt.OpenHandCursor)
            if ln:
                info = f"링크: {ln.get('uri') or str(ln.get('page', 0) + 1) + ' 페이지'}"
        else:
            self.setCursor(self._cursor_for_tool())
            if self.tool == TOOL_PLACE:
                self.update()
        if new_hover is not self.hover:
            self.hover = new_hover
            if isinstance(new_hover, TextItem):
                kind = "스캔(OCR) 텍스트" if new_hover.invisible else new_hover.font
                info = f"{kind} · {new_hover.size:.1f}pt — 클릭: 바로 수정 · 끌기: 이동 · 우클릭: 메뉴"
            elif isinstance(new_hover, ImageItem):
                info = f"이미지 {new_hover.width}×{new_hover.height}px — 클릭해 선택, 드래그로 이동, 우클릭 메뉴"
            elif isinstance(new_hover, AnnotItem):
                info = f"{new_hover.name} 주석 — 클릭해 선택, 우클릭으로 색 변경/삭제" + (
                    f" · 내용: {new_hover.content[:40]}" if new_hover.content else "")
            elif isinstance(new_hover, WidgetItem):
                info = f"양식 필드 '{new_hover.name}' — 클릭하여 입력"
            self.update()
        if info or new_hover is None:
            self.hoverInfo.emit(info)

    @staticmethod
    def _resized(r0, corner, p, keep_ratio):
        fixed = {"tl": r0.bottomRight(), "tr": r0.bottomLeft(), "bl": r0.topRight(), "br": r0.topLeft()}[corner]
        w, h = p.x() - fixed.x(), p.y() - fixed.y()
        if keep_ratio and r0.width() > 0 and r0.height() > 0:
            ratio = r0.width() / r0.height()
            if abs(w) / ratio > abs(h):
                h = abs(w) / ratio * (1 if h >= 0 else -1)
            else:
                w = abs(h) * ratio * (1 if w >= 0 else -1)
        r = QRectF(fixed, QPointF(fixed.x() + w, fixed.y() + h)).normalized()
        r.setWidth(max(5, r.width()))
        r.setHeight(max(5, r.height()))
        return r

    def mousePressEvent(self, ev):
        if not self.pdf or not self.pdf.doc:
            return
        if ev.button() == Qt.LeftButton and self._near_frame(ev.position()):
            self._drag = ("framemove", ev.position(), ev.globalPosition().toPoint())
            return
        if self.before_press is not None:
            self.before_press()
        self.focused.emit()
        self.setFocus()
        p = ev.position()
        pt = self.to_pdf(p)
        if ev.button() == Qt.RightButton:
            self._right_click(pt, ev.globalPosition().toPoint())
            return
        if ev.button() == Qt.MiddleButton:
            self._drag = ("pan", p, ev.globalPosition())
            return
        if ev.button() != Qt.LeftButton:
            return
        t = self.tool
        if t == TOOL_HAND:
            ln = self.link_at(pt)
            if ln:
                self.linkClicked.emit(ln)
                return
            w = self.widget_at(pt)
            if w:
                self.widgetClicked.emit(w)
                return
            self.setCursor(Qt.ClosedHandCursor)
            self._drag = ("pan", p, ev.globalPosition())
        elif t == TOOL_SELECT:
            self._press_select(p, pt, ev)
        elif t == TOOL_ADD_TEXT:
            self._drag = ("addtext", p, None)
            self._preview = QRectF(p, p)
        elif t == TOOL_NOTE:
            self.noteAt.emit(pt)
        elif t == TOOL_PLACE and self.place_size:
            w, h = self.place_size
            c = pymupdf.Point(p.x() / self.zoom, p.y() / self.zoom)
            r = pymupdf.Rect(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2) * self._page().derotation_matrix
            self.placeAt.emit(r.normalize())
        elif t in (TOOL_SELECT_TEXT, *MARKUP_TOOLS):
            self.text_sel, self.text_sel_str = [], ""
            self._drag = ("text", p, None)
        elif t == TOOL_PEN:
            self._stroke = [p]
            self._drag = ("pen", p, None)
        elif t in SHAPE_TOOLS:
            self._drag = ("shape", p, SHAPE_TOOLS[t])
            self._drag_end = p
        elif t in RUBBER_TOOLS:
            self._drag = ("rubber", p, None)
            self._preview = QRectF(p, p)

    def _press_select(self, p, pt, ev):
        sel = self.sel_image or (self.sel_annot if self.sel_annot and self.sel_annot.movable else None)
        if sel:
            h = self._handle_at(p, sel.bbox)
            if h:
                self._drag = ("resize", p, (h, self.to_view(sel.bbox)))
                return
            if sel.bbox.contains(pt):
                self._drag = ("move", p, self.to_view(sel.bbox))
                return
        w = self.widget_at(pt)
        if w:
            self.widgetClicked.emit(w)
            return
        if ev.modifiers() & Qt.ControlModifier:
            ln = self.link_at(pt)
            if ln:
                self.linkClicked.emit(ln)
                return
        a = self.annot_at(pt)
        if a:
            self.sel_image = None
            self.sel_annot = a
            if a.movable:
                self._drag = ("move", p, self.to_view(a.bbox))
            self.update()
            return
        t = self.text_at(pt)
        if t:
            self.sel_image = self.sel_annot = None
            self.text_sel, self.text_sel_str = [], ""
            self.update()
            # 바로 수정할지, 끌어서 옮길지는 놓을 때 결정
            self._drag = ("textpress", p, t)
            return
        self.text_sel, self.text_sel_str = [], ""
        im = self.image_at(pt)
        self.sel_annot = None
        self.sel_image = im
        if im:
            self._drag = ("move", p, self.to_view(im.bbox))
        self.update()

    def _right_click(self, pt, gpos):
        if self.tool in (TOOL_SELECT_TEXT, *MARKUP_TOOLS) and self.text_sel:
            if any((r + (-2, -2, 2, 2)).contains(pt) for r in self.text_sel):
                self.selectionContext.emit(gpos)
                return
        if self.sel_image and self.sel_image.bbox.contains(pt):
            self.imageContext.emit(self.sel_image, gpos)
            return
        a = self.annot_at(pt)
        if a:
            self.sel_annot, self.sel_image = a, None
            self.update()
            self.annotContext.emit(a, gpos)
            return
        t = self.text_at(pt)
        if t and self.tool in (TOOL_SELECT, TOOL_HAND, TOOL_SELECT_TEXT):
            self.textContext.emit(t, gpos)
            return
        im = self.image_at(pt)
        if im and self.tool == TOOL_SELECT:
            self.sel_image, self.sel_annot = im, None
            self.update()
            self.imageContext.emit(im, gpos)
            return
        self.emptyContext.emit(pt, gpos)

    def mouseReleaseEvent(self, ev):
        if not self._drag:
            return
        kind, start, extra = self._drag
        prev = self._preview
        self._drag = None
        self._preview = None
        p = ev.position()
        if kind == "pan" or kind == "framemove":
            self.setCursor(self._cursor_for_tool())
        elif kind == "textpress":
            self.textClicked.emit(extra)
        elif kind == "textmove":
            item = extra[0]
            if prev is not None:
                d_view = prev.topLeft() - extra[1].topLeft()
                d = self.to_pdf(d_view) - self.to_pdf(QPointF(0, 0))
                self.setCursor(Qt.IBeamCursor)
                if abs(d.x) + abs(d.y) > 0.5:
                    self.textMoved.emit(item, d)
        elif kind == "addtext":
            w = abs(p.x() - start.x())
            x0 = min(p.x(), start.x())
            if w > 24:
                self.addTextBox.emit(self.to_pdf(QPointF(x0, start.y())), w / self.zoom)
            else:
                self.addTextAt.emit(self.to_pdf(start))
        elif kind == "rubber":
            if prev is not None and prev.width() > 4 and prev.height() > 4:
                self.rectDrawn.emit(self.tool, self.rect_to_pdf(prev))
            elif self.tool == TOOL_ADD_IMAGE:
                q = QRectF(start, QPointF(start.x() + 200 * self.zoom, start.y() + 150 * self.zoom))
                self.rectDrawn.emit(self.tool, self.rect_to_pdf(q))
        elif kind == "text":
            if self.text_sel:
                if self.tool in MARKUP_TOOLS:
                    rects, txt = self.text_sel, self.text_sel_str
                    self.text_sel, self.text_sel_str = [], ""
                    self.markupDrawn.emit(MARKUP_TOOLS[self.tool], rects, txt)
                else:
                    self.textSelected.emit(self.text_sel, self.text_sel_str)
        elif kind == "pen":
            pts = [self.to_pdf(q) for q in self._stroke]
            self._stroke = []
            if len(pts) > 1:
                self.inkDrawn.emit([pts])
        elif kind == "shape":
            end = getattr(self, "_drag_end", p)
            if (end - start).manhattanLength() > 4:
                self.shapeDrawn.emit(extra, self.to_pdf(start), self.to_pdf(end))
        elif kind in ("move", "resize") and prev is not None:
            sel = self.sel_image or self.sel_annot
            if sel is not None:
                old = self.to_view(sel.bbox)
                if (prev.topLeft() - old.topLeft()).manhattanLength() > 1.5 or abs(prev.width() - old.width()) > 1.5:
                    if sel is self.sel_image:
                        self.imageMoved.emit(sel, self.rect_to_pdf(prev))
                    else:
                        self.annotMoved.emit(sel, self.rect_to_pdf(prev))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if self.tool != TOOL_SELECT or not self.pdf:
            return
        pt = self.to_pdf(ev.position())
        a = self.annot_at(pt)
        if a:
            self.annotDoubleClicked.emit(a)
            return
        im = self.image_at(pt)
        if im and not self.text_at(pt):
            self.sel_image = im
            self.imageDoubleClicked.emit(im)
            return
        if not self.text_at(pt) and not self.widget_at(pt):
            # 빈 곳 더블클릭 → 그 자리에 텍스트 추가
            self.addTextAt.emit(pt)

    def _near_frame(self, p: QPointF) -> bool:
        """편집 중인 상자 테두리 근처(바깥쪽 8px)인지"""
        if self.edit_frame is None or self.frame_mover is None:
            return False
        outer = QRectF(self.edit_frame).adjusted(-9, -9, 9, 9)
        inner = QRectF(self.edit_frame).adjusted(1, 1, -1, -1)
        return outer.contains(p) and not inner.contains(p)

    def leaveEvent(self, _ev):
        if self.hover is not None or self.tool == TOOL_PLACE:
            self.hover = None
            self.update()

    def select_all_text(self):
        ws = self.pdf.words(self.pno)
        if ws:
            self.text_sel, self.text_sel_str = self.pdf.select_words(
                self.pno, pymupdf.Rect(ws[0][:4]).tl, pymupdf.Rect(ws[-1][:4]).br)
            self.update()
        return self.text_sel_str

    def clear_selection(self):
        self.sel_image = None
        self.sel_annot = None
        self.select_after = None
        self.text_sel, self.text_sel_str = [], ""
        self._preview = None
        self.update()
