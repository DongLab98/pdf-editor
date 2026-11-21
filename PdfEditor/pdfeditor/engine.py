"""PDF 편집 엔진 (GUI 와 독립). 모든 좌표는 PyMuPDF 의 '회전 전' 페이지 좌표."""
from __future__ import annotations

import glob
import io
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import pymupdf
from PIL import Image, ImageEnhance, ImageOps

from . import fontmgr
from .annots import AnnotMixin
from .fontmgr import FontChain, build_chain, write_text

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
MAX_UNDO = 40


@dataclass
class TextItem:
    bbox: pymupdf.Rect
    text: str
    font: str
    size: float
    color: int
    flags: int
    origin: pymupdf.Point
    direction: tuple
    invisible: bool = False   # OCR 로 만든 숨은 텍스트 (스캔 문서)
    on_image: bool = False    # 이미지 위에 놓인 텍스트
    lines: list = field(default_factory=list)   # [(bbox, origin, text)] 문단을 이루는 줄들
    pitch: float = 0.0        # 줄 간격(기준선 사이 거리)
    align: str = "left"       # left / center / right / justify
    hidden: bool = False      # 배경과 같은 색이라 보이지 않는 글자 (예: 회색 칸 안의 흰 글자) — 맨 뒤에 둘 것

    @property
    def tiny(self):
        return self.size < 4.0

    @property
    def boxed(self):
        """편집 모드에서 점선 상자를 그릴 항목인지"""
        return not (self.hidden or self.tiny or (self.invisible and not self.on_image))

    @property
    def is_para(self):
        return len(self.lines) > 1

    @property
    def bold(self):
        return fontmgr.style_of(self.font, self.flags)[0]

    @property
    def italic(self):
        return fontmgr.style_of(self.font, self.flags)[1]

    @property
    def rgb(self):
        c = self.color
        return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255


@dataclass
class ImageItem:
    bbox: pymupdf.Rect
    xref: int
    width: int
    height: int


@dataclass
class EditResult:
    chain_desc: str = ""
    warnings: list = field(default_factory=list)


def tessdata_dir():
    cands = [os.path.join(fontmgr.app_dir(), "tessdata"), os.environ.get("TESSDATA_PREFIX", "")]
    cands += glob.glob("/usr/share/tesseract-ocr/*/tessdata") + [r"C:\Program Files\Tesseract-OCR\tessdata"]
    for c in cands:
        if c and os.path.isdir(c) and glob.glob(os.path.join(c, "*.traineddata")):
            return c
    return None


def ocr_languages():
    d = tessdata_dir()
    if not d:
        return []
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(d, "*.traineddata"))
                  if not os.path.basename(p).startswith("osd"))


# 화면에 보이지 않는 글자 (한글 채움 문자, 폭 없는 공백 등) — 한글(HWP) 변환 PDF에 자주 들어 있음
_INVISIBLE = set("\u3164\u115f\u1160\uffa0\u2800\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063"
                 "\u2064\ufeff\u00ad\u034f\u180e")


def is_visible_char(ch: str) -> bool:
    if ch in _INVISIBLE or ch.isspace():
        return False
    cat = unicodedata.category(ch)
    return cat not in ("Zs", "Zl", "Zp", "Cc", "Cf", "Co", "Cn", "Cs")


def has_visible(text: str) -> bool:
    return any(is_visible_char(c) for c in text)


class PdfDocument(AnnotMixin):
    def __init__(self):
        self.doc: pymupdf.Document | None = None
        self.path: str | None = None
        self.undo_stack: list[bytes] = []
        self.redo_stack: list[bytes] = []
        self.dirty = False
        self.embedded: fontmgr.EmbeddedFonts | None = None
        self._text_cache: dict = {}
        self.was_encrypted = False
        self._words_cache: dict = {}

    # ------------------------------------------------------------------ 파일
    def open(self, path: str, password: str | None = None):
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as f:
            data = f.read()
        if ext in IMAGE_EXTS:
            img = pymupdf.open(stream=data, filetype=ext[1:])
            doc = pymupdf.open("pdf", img.convert_to_pdf())
            path = os.path.splitext(path)[0] + ".pdf"
        else:
            doc = pymupdf.open(stream=data, filetype="pdf")
        self.was_encrypted = bool(doc.needs_pass or doc.is_encrypted)
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise PermissionError("암호가 필요합니다")
            # 암호를 푼 상태로 메모리에 다시 적재 (저장 시 암호 제거)
            doc = pymupdf.open("pdf", doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE))
        self._set_doc(doc)
        self.path = path
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = ext in IMAGE_EXTS

    def new_blank(self):
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        self._set_doc(doc)
        self.path = None
        self.dirty = True

    def _set_doc(self, doc):
        if self.doc is not None and self.doc is not doc:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc = doc
        self._text_cache.clear()
        self._words_cache = {}
        if self.embedded is None:
            self.embedded = fontmgr.EmbeddedFonts(doc)
        else:
            self.embedded.invalidate(doc)

    def save(self, path: str | None = None, *, encrypt: dict | None = None, compress: str | None = None):
        """encrypt: {"user": 열기암호, "owner": 권한암호, "print": bool, "copy": bool, "modify": bool}
        compress: None / "low" / "medium" / "high" (이미지 재압축)"""
        path = path or self.path
        if not path:
            raise ValueError("저장 경로가 없습니다")
        out = pymupdf.open("pdf", self.doc.tobytes())
        try:
            out.subset_fonts()
        except Exception:
            pass
        if compress:
            dpi, q = {"low": (200, 85), "medium": (150, 75), "high": (100, 60)}[compress]
            try:
                out.rewrite_images(dpi_threshold=dpi + 20, dpi_target=dpi, quality=q)
            except Exception:
                pass
        kw = dict(garbage=4 if compress else 3, deflate=True, deflate_fonts=True, deflate_images=True)
        if compress:
            kw["clean"] = True
        if encrypt and (encrypt.get("user") or encrypt.get("owner")):
            perm = pymupdf.PDF_PERM_ACCESSIBILITY
            if encrypt.get("print", True):
                perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
            if encrypt.get("copy", True):
                perm |= pymupdf.PDF_PERM_COPY
            if encrypt.get("modify", True):
                perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ASSEMBLE
            owner = encrypt.get("owner") or encrypt.get("user")
            kw.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=owner,
                      user_pw=encrypt.get("user") or "", permissions=int(perm))
        tmp = path + ".tmp_save"
        out.save(tmp, **kw)
        out.close()
        os.replace(tmp, path)
        if encrypt is None and compress is None:
            self.path = path
            self.dirty = False

    # ------------------------------------------------------------- 실행 취소
    def snapshot(self):
        self._words_cache = {}
        self.undo_stack.append(self.doc.tobytes())
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.dirty = True
        self._text_cache.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.doc.tobytes())
        self._set_doc(pymupdf.open("pdf", self.undo_stack.pop()))
        self.dirty = True
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.doc.tobytes())
        self._set_doc(pymupdf.open("pdf", self.redo_stack.pop()))
        self.dirty = True
        return True

    # ------------------------------------------------------------- 조회
    @property
    def page_count(self):
        return len(self.doc) if self.doc else 0

    def page(self, pno) -> pymupdf.Page:
        return self.doc[pno]

    def text_items(self, pno: int, line_mode=False, para=False) -> list[TextItem]:
        """line_mode: 서식과 관계없이 줄 전체 / para: 같은 서식의 줄들을 문단으로 묶음"""
        key = (pno, line_mode, para)
        if key in self._text_cache:
            return self._text_cache[key]
        page = self.doc[pno]
        flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
        d = page.get_text("rawdict", flags=flags)
        hidden = []
        try:
            for s in page.get_texttrace():
                if s.get("type") == 3 or s.get("opacity", 1) == 0:
                    hidden.append(pymupdf.Rect(s["bbox"]))
        except Exception:
            pass
        img_rects = [it.bbox for it in self.image_items(pno)]
        items = []
        for b in d.get("blocks", []):
            block_lines = []  # 줄마다 그 줄에서 나온 항목 목록
            for ln in b.get("lines", []):
                spans = ln.get("spans", [])
                for s in spans:
                    s["text"] = "".join(c["c"] for c in s.get("chars", []))
                spans = [s for s in spans if s["text"].strip()]
                if not spans:
                    continue
                groups = [spans] if line_mode else [[s] for s in spans]
                line_items = []
                for g in groups:
                    main = max(g, key=lambda s: len(s["text"].strip()))
                    allc = [c for s in ln["spans"] if (line_mode or s is g[0]) for c in s.get("chars", [])]
                    for chars in self._split_gaps(allc, main["size"]):
                        self._add_item(line_items, chars, main, ln, hidden, img_rects)
                block_lines.append(line_items)
            if para:
                items += self._merge_paragraphs(block_lines)
            else:
                for li in block_lines:
                    items += li
        self._mark_hidden(page, items)
        self._text_cache[key] = items
        return items

    def _mark_hidden(self, page, items):
        """글자색이 배경색과 거의 같으면(흰 바탕의 흰 글자 등) 숨은 글자로 표시."""
        light = [it for it in items if not it.invisible and sum(it.rgb) > 2.4]
        if not light:
            return
        try:
            pix = page.get_pixmap(dpi=36, alpha=False, colorspace=pymupdf.csRGB)
        except Exception:
            return
        sx, sy = pix.width / page.rect.width, pix.height / page.rect.height
        for it in light:
            r = it.bbox * page.rotation_matrix
            r.normalize()
            x0, y0 = int(r.x0 * sx), int(r.y0 * sy)
            x1, y1 = max(x0 + 1, int(r.x1 * sx)), max(y0 + 1, int(r.y1 * sy))
            dark = 0
            n = 0
            for y in range(max(0, y0), min(pix.height, y1)):
                for x in range(max(0, x0), min(pix.width, x1)):
                    c = pix.pixel(x, y)
                    n += 1
                    if max(abs(c[i] / 255 - it.rgb[i]) for i in range(3)) > 0.12:
                        dark += 1
            # 글자 영역이 거의 전부 글자색과 같은 색 → 배경과 구분 안 됨
            if n and dark / n > 0.85:
                continue
            if n:
                it.hidden = True

    @staticmethod
    def _same_style(a: TextItem, b: TextItem):
        return (a.font == b.font and abs(a.size - b.size) < 0.3 and a.color == b.color
                and a.direction == b.direction and a.invisible == b.invisible)

    def _merge_paragraphs(self, block_lines):
        """한 블록 안에서, 줄마다 서식이 하나뿐이고 서식이 같은 연속된 줄을 문단으로 묶음."""
        out, group = [], []

        def flush():
            if not group:
                return
            if len(group) == 1:
                out.append(group[0])
            else:
                out.append(self._make_para(group))
            group.clear()
        for li in block_lines:
            if len(li) != 1:
                flush()
                out += li
                continue
            it = li[0]
            if group:
                prev = group[-1]
                gap = it.origin.y - prev.origin.y
                pitch0 = group[1].origin.y - group[0].origin.y if len(group) > 1 else gap
                ok = (self._same_style(prev, it) and it.direction == (1.0, 0.0)
                      and it.size * 0.8 < gap < it.size * 2.6 and abs(gap - pitch0) < it.size * 0.35)
                if not ok:
                    flush()
            group.append(it)
        flush()
        return out

    def _make_para(self, group: list[TextItem]) -> TextItem:
        first = group[0]
        bbox = pymupdf.Rect()
        for g in group:
            bbox |= g.bbox
        pitch = (group[-1].origin.y - first.origin.y) / (len(group) - 1)
        # 정렬 감지
        x0s = [g.bbox.x0 for g in group]
        x1s = [g.bbox.x1 for g in group]
        cs = [(g.bbox.x0 + g.bbox.x1) / 2 for g in group]
        tol = first.size * 0.25
        if max(x0s) - min(x0s) < tol and max(x1s[:-1] or x1s) - min(x1s[:-1] or x1s) < tol and len(group) > 2:
            align = "justify"
        elif max(x0s[1:] or x0s) - min(x0s[1:] or x0s) < tol:
            align = "left"
        elif max(cs) - min(cs) < tol:
            align = "center"
        elif max(x1s) - min(x1s) < tol:
            align = "right"
        else:
            align = "left"
        # 줄 잇기: 줄 끝 하이픈(영문)은 붙이고, 나머지는 공백으로 (대부분 문서는 띄어쓰기에서 줄바꿈)
        text = group[0].text
        for prev, cur in zip(group, group[1:]):
            b = cur.text[:1]
            if prev.text.endswith("-") and b.isalpha() and b.isascii():
                text = text[:-1] + cur.text
            else:
                text += " " + cur.text
        lines = [(g.bbox, g.origin, g.text) for g in group]
        return TextItem(bbox, text, first.font, first.size, first.color, first.flags, first.origin, first.direction,
                        first.invisible, first.on_image, lines, pitch, align)

    @staticmethod
    def _split_gaps(chars, size):
        """표 칸처럼 멀리 떨어진 글자 묶음을 분리."""
        out, cur, last_x1 = [], [], None
        for c in chars:
            b = c["bbox"]
            # 공백 글자 없이 글자 크기의 30% 이상 떨어져 있으면 다른 칸/단으로 봄
            if last_x1 is not None and c["c"].strip() and b[0] - last_x1 > size * 0.3:
                out.append(cur)
                cur = []
            cur.append(c)
            last_x1 = b[2]
        out.append(cur)
        res = []
        for cs in out:
            nz = [i for i, c in enumerate(cs) if c["c"].strip()]
            if nz:
                res.append(cs[nz[0]: nz[-1] + 1])
        return res

    def _add_item(self, items, chars, main, ln, hidden, img_rects):
        # 보이지 않는 글자만 있는 묶음은 건너뜀, 앞뒤의 보이지 않는 글자는 잘라냄
        vis = [i for i, c in enumerate(chars) if is_visible_char(c["c"])]
        if not vis:
            return
        chars = chars[vis[0]: vis[-1] + 1]
        text = "".join(" " if (c["c"] == "\xa0" or c["c"] in _INVISIBLE) else c["c"] for c in chars)
        origin = pymupdf.Point(chars[0]["origin"])
        bbox = pymupdf.Rect()
        for c in chars:
            if is_visible_char(c["c"]):
                bbox |= pymupdf.Rect(c["bbox"])
        if bbox.is_empty or bbox.width < 0.3:
            return
        inv = any(self._overlap(bbox, h) > 0.5 for h in hidden)
        on_img = any(self._overlap(bbox, r) > 0.8 for r in img_rects)
        it = TextItem(bbox, text, main["font"], main["size"], main["color"], main["flags"],
                      origin, tuple(ln.get("dir", (1, 0))), inv, on_img)
        it.lines = [(bbox, origin, text)]
        it.pitch = main["size"] * 1.25
        items.append(it)

    @staticmethod
    def _overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
        inter = pymupdf.Rect(a) & b
        if inter.is_empty or a.is_empty:
            return 0.0
        return inter.get_area() / max(a.get_area(), 1e-6)

    def image_items(self, pno) -> list[ImageItem]:
        page = self.doc[pno]
        out = []
        try:
            for info in page.get_image_info(xrefs=True):
                r = pymupdf.Rect(info["bbox"])
                if r.is_empty or r.width < 1 or r.height < 1:
                    continue
                if info.get("width", 0) <= 1 and info.get("height", 0) <= 1:
                    continue  # 삭제된 이미지 자리표시
                out.append(ImageItem(r, info.get("xref", 0), info.get("width", 0), info.get("height", 0)))
        except Exception:
            pass
        return out

    def chain_for(self, item: TextItem | None, override: fontmgr.SysFont | None = None) -> FontChain:
        if item is None or item.invisible:
            name = "" if item is None else ""
            return build_chain(name, 0 if item is None else item.flags & ~1, None, override)
        return build_chain(item.font, item.flags, self.embedded, override)

    # ------------------------------------------------------------- 색상 추출
    def sample_colors(self, pno: int, rect: pymupdf.Rect):
        """영역의 배경색과 글자색 추정 (스캔 문서 편집용)."""
        page = self.doc[pno]
        r = pymupdf.Rect(rect) + (-2, -2, 2, 2)
        clip = r * page.rotation_matrix
        clip.normalize()
        clip &= page.rect
        try:
            pix = page.get_pixmap(clip=clip, dpi=144, alpha=False, colorspace=pymupdf.csRGB)
        except Exception:
            return (1, 1, 1), (0, 0, 0)
        w, h, s = pix.width, pix.height, pix.samples
        if w < 3 or h < 3:
            return (1, 1, 1), (0, 0, 0)

        def px(x, y):
            i = (y * w + x) * 3
            return s[i], s[i + 1], s[i + 2]
        border = [px(x, 0) for x in range(w)] + [px(x, h - 1) for x in range(w)] + \
                 [px(0, y) for y in range(h)] + [px(w - 1, y) for y in range(h)]
        q = Counter((c[0] // 16, c[1] // 16, c[2] // 16) for c in border)
        top = q.most_common(1)[0][0]
        sel = [c for c in border if (c[0] // 16, c[1] // 16, c[2] // 16) == top]
        bg = tuple(sum(c[i] for c in sel) / len(sel) for i in range(3))
        fg_px = []
        for y in range(1, h - 1, 1):
            for x in range(1, w - 1, 1):
                c = px(x, y)
                if sum(abs(c[i] - bg[i]) for i in range(3)) > 160:
                    fg_px.append(c)
        if fg_px:
            # 가장 진한 쪽 절반의 평균
            fg_px.sort(key=lambda c: sum(abs(c[i] - bg[i]) for i in range(3)), reverse=True)
            fg_px = fg_px[: max(1, len(fg_px) // 2)]
            fg = tuple(sum(c[i] for c in fg_px) / len(fg_px) / 255 for i in range(3))
        else:
            fg = (0, 0, 0)
        return tuple(v / 255 for v in bg), fg

    # ------------------------------------------------------------- 텍스트 편집
    def _remove_text(self, page: pymupdf.Page, rect: pymupdf.Rect):
        h = rect.height
        r = pymupdf.Rect(rect.x0 + 0.2, rect.y0 + h * 0.25, rect.x1 - 0.2, rect.y1 - h * 0.25)
        page.add_redact_annot(r, fill=False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    def _remove_item(self, page, item: TextItem, fill=None):
        rects = [ln[0] for ln in item.lines] or [item.bbox]
        for r in rects:
            h = r.height
            page.add_redact_annot(pymupdf.Rect(r.x0 + 0.2, r.y0 + h * 0.25, r.x1 - 0.2, r.y1 - h * 0.25),
                                  fill=False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        if fill is not None:
            for r in rects:
                page.draw_rect(r + (-2, -1.5, 2, 1.5), color=None, fill=fill, overlay=True)

    def write_paragraph(self, pno: int, item: TextItem | None, lines: list[str], *, origin, box_width: float,
                        chain: FontChain, size: float, color, pitch: float, align="left", direction=(1.0, 0.0),
                        synth_bold=False, synth_italic=False, underline=False, fill=None,
                        first_indent=0.0) -> EditResult:
        """줄 목록(이미 줄바꿈된)을 정렬·줄간격·서식대로 씀. item 이 있으면 원래 글자를 지우고 그 자리에."""
        self.snapshot()
        page = self.doc[pno]
        if item is not None:
            self._remove_item(page, item, fill)
        offsets = []
        plan = chain.plan("".join(lines))
        for i, ln in enumerate(lines):
            w = fontmgr.text_width(ln, chain, size, plan)
            if align == "center":
                offsets.append((box_width - w) / 2)
            elif align == "right":
                offsets.append(box_width - w)
            else:
                offsets.append(first_indent if i == 0 else 0.0)
        if any(ln.strip() for ln in lines):
            fontmgr.write_block(page, origin, lines, chain, size, color, direction, pitch, offsets,
                                synth_bold, synth_italic, underline,
                                justify_width=box_width if align == "justify" else None)
        self._text_cache.clear()
        return EditResult(chain.describe("".join(lines)))

    def replace_text(self, pno: int, item: TextItem, new_text: str, *, size: float | None = None,
                     color=None, chain: FontChain | None = None, fill=None, snapshot=True) -> EditResult:
        """기존 텍스트를 지우고 같은 위치/글꼴/크기/색으로 새 텍스트를 씀.
        fill: None 이면 배경 그대로(일반 PDF), 색 튜플이면 그 색으로 덮음(스캔 문서)."""
        if snapshot:
            self.snapshot()
        page = self.doc[pno]
        size = size or item.size
        color = item.rgb if color is None else color
        chain = chain or self.chain_for(item)
        self._remove_item(page, item, fill)
        if new_text.strip():
            write_text(page, item.origin, new_text, chain, size, color, item.direction)
        self._text_cache.clear()
        return EditResult(chain.describe(new_text))

    def delete_text(self, pno: int, item: TextItem, fill=None):
        self.snapshot()
        page = self.doc[pno]
        self._remove_item(page, item, fill)
        self._text_cache.clear()

    def add_text(self, pno: int, point: pymupdf.Point, text: str, size: float, color, chain: FontChain) -> EditResult:
        self.snapshot()
        page = self.doc[pno]
        origin = pymupdf.Point(point.x, point.y + size * 0.88)
        write_text(page, origin, text, chain, size, color)
        self._text_cache.clear()
        return EditResult(chain.describe(text))

    def nearby_style(self, pno: int, point: pymupdf.Point) -> TextItem | None:
        """새 텍스트 추가 시, 가장 가까운 기존 텍스트의 글꼴/크기를 기본값으로."""
        best, bd = None, 1e9
        for it in self.text_items(pno, False):
            if it.invisible or it.hidden or it.size < 6 or it.direction != (1.0, 0.0):
                continue
            # 사각형까지의 거리
            dx = max(it.bbox.x0 - point.x, 0, point.x - it.bbox.x1)
            dy = max(it.bbox.y0 - point.y, 0, point.y - it.bbox.y1)
            dd = (dx * dx + dy * dy) ** 0.5
            if dd < bd:
                best, bd = it, dd
        return best if bd < 120 else None

    def move_text(self, pno: int, item: TextItem, delta: pymupdf.Point) -> EditResult:
        """텍스트 상자를 같은 글꼴·크기·색 그대로 옮김."""
        self.snapshot()
        page = self.doc[pno]
        fill = self.sample_colors(pno, item.bbox)[0] if (item.invisible or item.on_image) else None
        color = item.rgb
        if item.invisible:
            color = self.sample_colors(pno, item.bbox)[1]
        chain = self.chain_for(item)
        self._remove_item(page, item, fill)
        lines = item.lines or [(item.bbox, item.origin, item.text)]
        for _bbox, origin, text in lines:
            fontmgr.write_block(page, pymupdf.Point(origin) + delta, [text], chain, item.size, color, item.direction)
        self._text_cache.clear()
        return EditResult(chain.describe(item.text))

    def erase_area(self, pno: int, rect: pymupdf.Rect, fill=(1, 1, 1)):
        self.snapshot()
        page = self.doc[pno]
        page.add_redact_annot(rect, fill=fill if fill is not None else False, cross_out=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        self._text_cache.clear()

    # ------------------------------------------------------------- 이미지
    def image_pil(self, xref: int) -> Image.Image:
        pix = pymupdf.Pixmap(self.doc, xref)
        try:
            smask = self.doc.extract_image(xref).get("smask", 0)
        except Exception:
            smask = 0
        if pix.colorspace and pix.colorspace.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        if smask:
            try:
                mask = pymupdf.Pixmap(self.doc, smask)
                if pix.alpha:
                    pix = pymupdf.Pixmap(pix, 0)
                pix = pymupdf.Pixmap(pix, mask)
            except Exception:
                pass
        mode = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[pix.n]
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples)

    @staticmethod
    def _pil_bytes(img: Image.Image) -> bytes:
        bio = io.BytesIO()
        if img.mode in ("RGBA", "LA") or "transparency" in img.info:
            img.save(bio, "PNG", optimize=True)
        else:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(bio, "JPEG", quality=92) if img.width * img.height > 250000 else img.save(bio, "PNG")
        return bio.getvalue()

    def _remove_image(self, page: pymupdf.Page, xref: int):
        """페이지 내용에서 이미지 그리기 명령(/ImN Do)을 제거. 실패 시 PyMuPDF delete_image."""
        name = None
        for img in page.get_images(full=True):
            if img[0] == xref and img[-1] == 0:
                name = img[7]
                break
        if name:
            page.clean_contents()
            pat = re.compile(rb"/" + re.escape(name.encode()) + rb"\s+Do\b")
            done = False
            for cx in page.get_contents():
                data = self.doc.xref_stream(cx)
                new = pat.sub(b"", data)
                if new != data:
                    self.doc.update_stream(cx, new)
                    done = True
            if done:
                return
        page.delete_image(xref)

    def insert_image(self, pno: int, rect: pymupdf.Rect, filename: str, keep_proportion=True):
        self.snapshot()
        page = self.doc[pno]
        img = Image.open(filename)
        img.load()
        if keep_proportion:
            # 사각형 안에 비율 맞춰 넣되, 실제 배치 사각형을 계산 (이후 선택/이동 편하게)
            iw, ih = img.size
            s = min(rect.width / iw, rect.height / ih)
            w, h = iw * s, ih * s
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + w, rect.y0 + h)
        page.insert_image(rect, stream=self._pil_bytes(img), keep_proportion=False)
        self._text_cache.clear()
        return rect

    def move_image(self, pno: int, item: ImageItem, new_rect: pymupdf.Rect):
        self.snapshot()
        page = self.doc[pno]
        img = self.image_pil(item.xref)
        self._remove_image(page, item.xref)
        page.insert_image(new_rect, stream=self._pil_bytes(img), keep_proportion=False)
        self._text_cache.clear()

    def delete_image(self, pno: int, item: ImageItem):
        self.snapshot()
        self._remove_image(self.doc[pno], item.xref)
        self._text_cache.clear()

    def replace_image(self, pno: int, item: ImageItem, filename: str, keep_box=True):
        img = Image.open(filename)
        img.load()
        self._apply_new_image(pno, item, img, keep_box)

    def transform_image(self, pno: int, item: ImageItem, op: str, **kw):
        img = self.image_pil(item.xref)
        if op == "rotate_cw":
            img = img.transpose(Image.Transpose.ROTATE_270)
        elif op == "rotate_ccw":
            img = img.transpose(Image.Transpose.ROTATE_90)
        elif op == "flip_h":
            img = ImageOps.mirror(img)
        elif op == "flip_v":
            img = ImageOps.flip(img)
        elif op == "gray":
            a = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
            img = ImageOps.grayscale(img.convert("RGB"))
            if a is not None:
                img = img.convert("LA")
                img.putalpha(a)
        elif op == "invert":
            a = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
            img = ImageOps.invert(img.convert("RGB"))
            if a is not None:
                img.putalpha(a)
        elif op == "adjust":
            a = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
            base = img.convert("RGB")
            base = ImageEnhance.Brightness(base).enhance(kw.get("brightness", 1.0))
            base = ImageEnhance.Contrast(base).enhance(kw.get("contrast", 1.0))
            base = ImageEnhance.Color(base).enhance(kw.get("saturation", 1.0))
            base = ImageEnhance.Sharpness(base).enhance(kw.get("sharpness", 1.0))
            if a is not None:
                base.putalpha(a)
            img = base
        elif op == "crop":
            # kw["box"]: 0~1 비율 (left, top, right, bottom)
            l, t, r, b = kw["box"]
            W, H = img.size
            img = img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
            ob = item.bbox
            nb = pymupdf.Rect(ob.x0 + l * ob.width, ob.y0 + t * ob.height, ob.x0 + r * ob.width, ob.y0 + b * ob.height)
            self.snapshot()
            page = self.doc[pno]
            self._remove_image(page, item.xref)
            page.insert_image(nb, stream=self._pil_bytes(img), keep_proportion=False)
            self._text_cache.clear()
            return
        self._apply_new_image(pno, item, img, keep_box=op not in ("rotate_cw", "rotate_ccw"))

    def _apply_new_image(self, pno, item: ImageItem, img: Image.Image, keep_box: bool):
        self.snapshot()
        page = self.doc[pno]
        r = item.bbox
        if keep_box:
            nb = r
        else:  # 비율 변화 (회전 등) -> 같은 중심, 같은 면적 비율
            iw, ih = img.size
            s = min(r.width, r.height) if False else (r.width * r.height / (iw * ih)) ** 0.5
            w, h = iw * s, ih * s
            c = (r.tl + r.br) / 2
            nb = pymupdf.Rect(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)
        self._remove_image(page, item.xref)
        page.insert_image(nb, stream=self._pil_bytes(img), keep_proportion=False)
        self._text_cache.clear()

    def export_image(self, item: ImageItem, path: str):
        img = self.image_pil(item.xref)
        if path.lower().endswith((".jpg", ".jpeg")) and img.mode != "RGB":
            img = img.convert("RGB")
        img.save(path)

    # ------------------------------------------------------------- OCR
    def ocr_page(self, pno: int, language="kor+eng", dpi=300, snapshot=True) -> str:
        tess = tessdata_dir()
        if not tess:
            raise RuntimeError("OCR 언어 데이터(tessdata)를 찾을 수 없습니다.")
        page = self.doc[pno]
        native = [it.bbox for it in self.text_items(pno, False) if not it.invisible]
        old_hidden = [it.bbox for it in self.text_items(pno, False) if it.invisible]
        full = len(native) == 0
        tp = page.get_textpage_ocr(flags=pymupdf.TEXT_PRESERVE_WHITESPACE, language=language, dpi=dpi,
                                   full=full, tessdata=tess)
        d = page.get_text("dict", textpage=tp)
        lines = []
        for b in d.get("blocks", []):
            for ln in b.get("lines", []):
                text = "".join(s["text"] for s in ln.get("spans", [])).strip()
                if not text:
                    continue
                bbox = pymupdf.Rect(ln["bbox"])
                if any(self._overlap(bbox, n) > 0.3 for n in native + old_hidden):
                    continue
                lines.append((bbox, text, tuple(ln.get("dir", (1, 0)))))
        del tp
        if snapshot:
            self.snapshot()
        if lines:
            font = pymupdf.Font("cjk")
            tw = pymupdf.TextWriter(page.rect)
            for bbox, text, _dir in lines:
                unit = font.text_length(text, fontsize=1)
                if unit <= 0:
                    continue
                fs = bbox.width / unit
                if fs > bbox.height * 1.6 or fs < bbox.height * 0.3:
                    fs = bbox.height * 0.85
                origin = pymupdf.Point(bbox.x0, bbox.y1 - bbox.height * 0.2)
                tw.append(origin, text, font=font, fontsize=fs)
            tw.write_text(page, render_mode=3)
        self._text_cache.clear()
        return "\n".join(t for _b, t, _d in lines)

    def page_text(self, pno: int) -> str:
        return self.doc[pno].get_text("text", sort=True)

    # ------------------------------------------------------------- 페이지
    def rotate_page(self, pno: int, delta=90):
        self.snapshot()
        p = self.doc[pno]
        p.set_rotation((p.rotation + delta) % 360)

    def delete_page(self, pno: int):
        if self.page_count <= 1:
            raise ValueError("마지막 한 페이지는 삭제할 수 없습니다")
        self.snapshot()
        self.doc.delete_page(pno)

    def insert_blank(self, after: int):
        self.snapshot()
        r = self.doc[after].rect if self.page_count else pymupdf.paper_rect("a4")
        self.doc.new_page(after + 1, width=r.width, height=r.height)

    def insert_pdf(self, after: int, path: str):
        self.snapshot()
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS:
            img = pymupdf.open(path)
            src = pymupdf.open("pdf", img.convert_to_pdf())
        else:
            src = pymupdf.open(path)
        self.doc.insert_pdf(src, start_at=after + 1)
        return len(src)

    def move_page(self, pno: int, to: int):
        if to < 0 or to >= self.page_count or to == pno:
            return
        self.snapshot()
        self.doc.move_page(pno, to if to < pno else to + 1)

    def export_page_png(self, pno: int, path: str, dpi=200):
        self.doc[pno].get_pixmap(dpi=dpi).save(path)

    def search(self, needle: str):
        res = []
        for i in range(self.page_count):
            for q in self.doc[i].search_for(needle):
                res.append((i, q))
        return res
