"""주석(형광펜·밑줄·취소선·메모·펜·도형·링크), 텍스트 선택, 양식 필드.
PdfDocument 에 섞어 쓰는 Mixin."""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf

AUTHOR = "PDF 편집기"

# 이동(드래그) 가능한 주석 종류
MOVABLE = {pymupdf.PDF_ANNOT_SQUARE, pymupdf.PDF_ANNOT_CIRCLE, pymupdf.PDF_ANNOT_TEXT,
           pymupdf.PDF_ANNOT_FREE_TEXT, pymupdf.PDF_ANNOT_STAMP}
ANNOT_NAMES = {
    pymupdf.PDF_ANNOT_HIGHLIGHT: "형광펜", pymupdf.PDF_ANNOT_UNDERLINE: "밑줄",
    pymupdf.PDF_ANNOT_STRIKE_OUT: "취소선", pymupdf.PDF_ANNOT_SQUIGGLY: "물결 밑줄",
    pymupdf.PDF_ANNOT_TEXT: "메모", pymupdf.PDF_ANNOT_INK: "펜", pymupdf.PDF_ANNOT_SQUARE: "사각형",
    pymupdf.PDF_ANNOT_CIRCLE: "원", pymupdf.PDF_ANNOT_LINE: "선", pymupdf.PDF_ANNOT_FREE_TEXT: "텍스트 상자",
    pymupdf.PDF_ANNOT_STAMP: "스탬프", pymupdf.PDF_ANNOT_POLYGON: "다각형", pymupdf.PDF_ANNOT_POLY_LINE: "꺾은선",
}


@dataclass
class AnnotItem:
    xref: int
    type: int
    bbox: pymupdf.Rect
    content: str

    @property
    def name(self):
        return ANNOT_NAMES.get(self.type, "주석")

    @property
    def movable(self):
        return self.type in MOVABLE


@dataclass
class WidgetItem:
    xref: int
    bbox: pymupdf.Rect
    kind: int
    name: str
    value: object
    choices: list


class AnnotMixin:
    doc: pymupdf.Document
    _words_cache: dict

    # ------------------------------------------------------------- 텍스트 선택
    def words(self, pno):
        cache = self.__dict__.setdefault("_words_cache", {})
        if pno not in cache:
            from .engine import _INVISIBLE, has_visible
            ws = []
            for w in self.doc[pno].get_text("words", sort=False):
                if not has_visible(w[4]):
                    continue  # 한글 채움 문자 등 보이지 않는 글자만 있는 낱말은 제외
                txt = "".join(" " if (ch == "\xa0" or ch in _INVISIBLE) else ch for ch in w[4]).strip()
                ws.append((*w[:4], txt, *w[5:]))
            cache[pno] = ws
        return cache[pno]

    def clear_words_cache(self):
        self.__dict__["_words_cache"] = {}

    def _nearest_word(self, ws, pt: pymupdf.Point):
        best, bd = None, 1e9
        for i, w in enumerate(ws):
            r = pymupdf.Rect(w[:4])
            if r.contains(pt):
                return i
            # 같은 줄(세로 범위 안)이면 가로 거리만, 아니면 큰 패널티
            dx = 0 if r.x0 <= pt.x <= r.x1 else min(abs(pt.x - r.x0), abs(pt.x - r.x1))
            dy = 0 if r.y0 <= pt.y <= r.y1 else min(abs(pt.y - r.y0), abs(pt.y - r.y1))
            d = dx + dy * 4
            if d < bd:
                best, bd = i, d
        return best

    def select_words(self, pno, p1: pymupdf.Point, p2: pymupdf.Point):
        """시작점~끝점 사이의 단어들을 읽는 순서대로 선택. (줄별 사각형 목록, 텍스트) 반환"""
        ws = self.words(pno)
        if not ws:
            return [], ""
        i, j = self._nearest_word(ws, p1), self._nearest_word(ws, p2)
        if i is None or j is None:
            return [], ""
        if i > j:
            i, j = j, i
        sel = ws[i: j + 1]
        lines, order, text_parts = {}, [], []
        last_key = None
        for w in sel:
            key = (w[5], w[6])
            if key not in lines:
                lines[key] = pymupdf.Rect(w[:4])
                order.append(key)
            else:
                lines[key] |= pymupdf.Rect(w[:4])
            if last_key is not None and key != last_key:
                text_parts.append("\n")
            elif last_key is not None:
                text_parts.append(" ")
            text_parts.append(w[4])
            last_key = key
        return [lines[k] for k in order], "".join(text_parts)

    # ------------------------------------------------------------- 주석 추가
    def _finish(self, annot, color=None, opacity=None, width=None, fill=None):
        if color is not None:
            if fill is not None:
                annot.set_colors(stroke=color, fill=fill)
            else:
                annot.set_colors(stroke=color)
        if width is not None:
            annot.set_border(width=width)
        if opacity is not None:
            annot.set_opacity(opacity)
        annot.set_info(title=AUTHOR)
        annot.update()
        self._after_annot()
        return annot

    def _after_annot(self):
        self._text_cache.clear()  # type: ignore[attr-defined]
        self.clear_words_cache()

    def add_markup(self, pno, kind: str, rects, color, opacity=None):
        """kind: highlight / underline / strikeout / squiggly"""
        self.snapshot()  # type: ignore[attr-defined]
        page = self.doc[pno]
        quads = [pymupdf.Rect(r).quad for r in rects]
        fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
              "strikeout": page.add_strikeout_annot, "squiggly": page.add_squiggly_annot}[kind]
        a = fn(quads)
        return self._finish(a, color, opacity if opacity is not None else (0.45 if kind == "highlight" else None))

    def add_note(self, pno, point, text, color=(1, 0.85, 0.2)):
        self.snapshot()  # type: ignore[attr-defined]
        a = self.doc[pno].add_text_annot(point, text, icon="Comment")
        a.set_info(content=text, title=AUTHOR)
        return self._finish(a, color)

    def add_ink(self, pno, strokes, color, width=2.0, opacity=None):
        self.snapshot()  # type: ignore[attr-defined]
        pts = [[(p.x, p.y) for p in s] for s in strokes if len(s) > 1]
        if not pts:
            return None
        a = self.doc[pno].add_ink_annot(pts)
        return self._finish(a, color, opacity, width)

    def add_shape(self, pno, kind, p1, p2, color, width=2.0, fill=None, opacity=None):
        """kind: rect / ellipse / line / arrow"""
        self.snapshot()  # type: ignore[attr-defined]
        page = self.doc[pno]
        if kind in ("rect", "ellipse"):
            r = pymupdf.Rect(p1, p2).normalize()
            a = page.add_rect_annot(r) if kind == "rect" else page.add_circle_annot(r)
            return self._finish(a, color, opacity, width, fill)
        a = page.add_line_annot(p1, p2)
        if kind == "arrow":
            a.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_CLOSED_ARROW)
            return self._finish(a, color, opacity, width, color)
        return self._finish(a, color, opacity, width)

    def add_link(self, pno, rect, uri=None, page_no=None):
        self.snapshot()  # type: ignore[attr-defined]
        page = self.doc[pno]
        if uri:
            page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(rect), "uri": uri})
        else:
            page.insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(rect), "page": int(page_no),
                              "to": pymupdf.Point(0, 0)})
        self._after_annot()

    def links(self, pno):
        return self.doc[pno].get_links()

    def delete_link(self, pno, link):
        self.snapshot()  # type: ignore[attr-defined]
        self.doc[pno].delete_link(link)

    # ------------------------------------------------------------- 주석 조회/편집
    def annot_items(self, pno) -> list[AnnotItem]:
        out = []
        for a in self.doc[pno].annots() or []:
            if a.type[0] in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_POPUP):
                continue
            out.append(AnnotItem(a.xref, a.type[0], pymupdf.Rect(a.rect), a.info.get("content", "")))
        return out

    def _annot(self, pno, xref):
        page = self.doc[pno]
        self._annot_page = page  # 페이지 객체가 사라지면 주석이 분리되므로 참조 유지
        return page.load_annot(xref)

    def annot_color(self, pno, item: AnnotItem):
        a = self._annot(pno, item.xref)
        c = a.colors.get("stroke") or a.colors.get("fill") or (1, 1, 0)
        return tuple(c[:3]) if len(c) >= 3 else (c[0],) * 3

    def set_annot_style(self, pno, item: AnnotItem, color=None, opacity=None, width=None, content=None):
        self.snapshot()  # type: ignore[attr-defined]
        a = self._annot(pno, item.xref)
        if color is not None:
            if a.type[0] in (pymupdf.PDF_ANNOT_LINE,) and a.colors.get("fill"):
                a.set_colors(stroke=color, fill=color)
            else:
                a.set_colors(stroke=color)
        if opacity is not None:
            a.set_opacity(opacity)
        if width is not None:
            a.set_border(width=width)
        if content is not None:
            a.set_info(content=content)
        a.update()
        self._after_annot()

    def move_annot(self, pno, item: AnnotItem, new_rect):
        self.snapshot()  # type: ignore[attr-defined]
        a = self._annot(pno, item.xref)
        a.set_rect(pymupdf.Rect(new_rect))
        a.update()
        self._after_annot()

    def delete_annot(self, pno, item: AnnotItem):
        self.snapshot()  # type: ignore[attr-defined]
        page = self.doc[pno]
        page.delete_annot(page.load_annot(item.xref))
        self._after_annot()

    def delete_all_annots(self, pno=None):
        self.snapshot()  # type: ignore[attr-defined]
        pages = range(len(self.doc)) if pno is None else [pno]
        n = 0
        for p in pages:
            page = self.doc[p]
            for a in list(page.annots() or []):
                if a.type[0] not in (pymupdf.PDF_ANNOT_WIDGET, pymupdf.PDF_ANNOT_LINK):
                    page.delete_annot(a)
                    n += 1
        self._after_annot()
        return n

    def flatten_annots(self):
        """주석을 페이지 내용에 합쳐 다른 프로그램에서도 똑같이 보이게 (더 이상 주석 편집 불가)."""
        self.snapshot()  # type: ignore[attr-defined]
        try:
            self.doc.bake(annots=True, widgets=False)
        except Exception:
            pass
        self._after_annot()

    # ------------------------------------------------------------- 양식
    def widget_items(self, pno) -> list[WidgetItem]:
        out = []
        for w in self.doc[pno].widgets() or []:
            try:
                ch = list(w.choice_values or [])
            except Exception:
                ch = []
            out.append(WidgetItem(w.xref, pymupdf.Rect(w.rect), w.field_type, w.field_name or "",
                                  w.field_value, ch))
        return out

    def set_widget_value(self, pno, item: WidgetItem, value):
        self.snapshot()  # type: ignore[attr-defined]
        page = self.doc[pno]
        for w in page.widgets():
            if w.xref == item.xref:
                if w.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX or w.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    w.field_value = w.on_state() if value else "Off"
                else:
                    w.field_value = value
                w.update()
                break
        self._after_annot()
