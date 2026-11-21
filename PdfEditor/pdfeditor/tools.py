"""문서 단위 도구: 합치기, 분할, 추출, 머리글/바닥글/페이지 번호, 워터마크, 새 PDF, 비교,
속성, 책갈피, 이미지 추출, 도장/서명 이미지."""
from __future__ import annotations

import datetime
import difflib
import html
import io
import os
import re

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from . import fontmgr
from .fontmgr import build_chain, text_width, write_text

PAPER = {"A4": (595, 842), "A3": (842, 1191), "A5": (420, 595), "B4": (729, 1032), "B5": (516, 729),
         "Letter": (612, 792), "Legal": (612, 1008)}


# ----------------------------------------------------------------------------- 페이지 범위
def parse_range(text: str, total: int) -> list[int]:
    """'1-3, 5, 8-' → 0부터 시작하는 페이지 번호 목록. 빈 문자열이면 전체."""
    text = (text or "").strip()
    if not text or text in ("전체", "all"):
        return list(range(total))
    out = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        if "-" in part or "~" in part:
            a, b = re.split(r"[-~]", part, 1)
            a = int(a) if a.strip() else 1
            b = int(b) if b.strip() else total
            if a > b:
                a, b = b, a
            out += list(range(a - 1, b))
        else:
            out.append(int(part) - 1)
    seen, res = set(), []
    for p in out:
        if 0 <= p < total and p not in seen:
            seen.add(p)
            res.append(p)
    if not res:
        raise ValueError("올바른 페이지 범위가 아닙니다")
    return res


def _open_any(path: str) -> pymupdf.Document:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return pymupdf.open(path)
    src = pymupdf.open(path)
    return pymupdf.open("pdf", src.convert_to_pdf())


# ----------------------------------------------------------------------------- 합치기/분할
def merge(paths: list[str], out_path: str, passwords: dict | None = None, bookmarks=True):
    out = pymupdf.open()
    toc = []
    for p in paths:
        src = _open_any(p)
        if src.needs_pass:
            pw = (passwords or {}).get(p)
            if not pw or not src.authenticate(pw):
                raise PermissionError(f"암호가 필요한 파일입니다: {os.path.basename(p)}")
        start = len(out)
        out.insert_pdf(src)
        if bookmarks:
            toc.append([1, os.path.splitext(os.path.basename(p))[0], start + 1])
            for lvl, title, page, *_ in src.get_toc(simple=True):
                toc.append([lvl + 1, title, start + page])
        src.close()
    if bookmarks and toc:
        try:
            out.set_toc(toc)
        except Exception:
            pass
    out.save(out_path, garbage=3, deflate=True)
    return len(out)


def split(doc: pymupdf.Document, out_dir: str, base: str, mode: str, value) -> list[str]:
    """mode: 'every' (value=N쪽씩) / 'ranges' (value='1-3,4-6' 각 범위마다 파일) / 'each' (한 쪽씩)"""
    total = len(doc)
    groups = []
    if mode == "each":
        groups = [[i] for i in range(total)]
    elif mode == "every":
        n = max(1, int(value))
        groups = [list(range(i, min(i + n, total))) for i in range(0, total, n)]
    else:
        for part in re.split(r"[,;]+", value):
            if part.strip():
                groups.append(parse_range(part, total))
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for gi, g in enumerate(groups, 1):
        out = pymupdf.open()
        for p in g:
            out.insert_pdf(doc, from_page=p, to_page=p)
        label = f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}-{g[-1] + 1}"
        path = os.path.join(out_dir, f"{base}_{gi:02d}_p{label}.pdf")
        out.save(path, garbage=3, deflate=True)
        files.append(path)
    return files


def extract_pages(doc: pymupdf.Document, pages: list[int], out_path: str):
    out = pymupdf.open()
    for p in pages:
        out.insert_pdf(doc, from_page=p, to_page=p)
    out.save(out_path, garbage=3, deflate=True)


def new_pdf(paper="A4", landscape=False, count=1, color=(1, 1, 1)) -> pymupdf.Document:
    w, h = PAPER.get(paper, PAPER["A4"])
    if landscape:
        w, h = h, w
    doc = pymupdf.open()
    for _ in range(max(1, count)):
        p = doc.new_page(width=w, height=h)
        if tuple(color) != (1, 1, 1):
            p.draw_rect(p.rect, color=None, fill=color)
    return doc


# ----------------------------------------------------------------------------- 머리글/바닥글
def _to_page(page, x, y, dx=1.0, dy=0.0):
    """화면(회전 반영) 좌표의 점/방향을 PDF 내부(회전 전) 좌표로."""
    m = page.derotation_matrix
    p = pymupdf.Point(x, y) * m
    o = pymupdf.Point(0, 0) * m
    d = pymupdf.Point(dx, dy) * m - o
    ln = (d.x ** 2 + d.y ** 2) ** 0.5 or 1
    return p, (round(d.x / ln, 6), round(d.y / ln, 6))


def _default_chain(bold=False):
    return build_chain("MalgunGothicBold" if bold else "MalgunGothic", 16 if bold else 0, None)


def _fmt(t: str, p: int, n: int, fname: str):
    return (t.replace("{p}", str(p)).replace("{n}", str(n))
             .replace("{date}", datetime.date.today().strftime("%Y-%m-%d")).replace("{file}", fname))


def header_footer(pdf, pages: list[int], spec: dict):
    """spec: {"header": [left, center, right], "footer": [l, c, r], "size": 10, "color": (r,g,b),
              "margin": 28, "start": 1}  텍스트 안 {p} 쪽번호, {n} 전체 쪽수, {date}, {file}"""
    pdf.snapshot()
    doc = pdf.doc
    size = float(spec.get("size", 10))
    color = spec.get("color", (0, 0, 0))
    margin = float(spec.get("margin", 28))
    start = int(spec.get("start", 1))
    chain = _default_chain()
    fname = os.path.splitext(os.path.basename(pdf.path or "문서"))[0]
    n = len(pages) + start - 1
    for idx, pno in enumerate(pages):
        page = doc[pno]
        # 표시 기준(회전 반영) 사각형에 배치 후 회전 해제 좌표로 변환
        R = page.rect
        num = idx + start
        for where, texts in (("header", spec.get("header", ["", "", ""])), ("footer", spec.get("footer", ["", "", ""]))):
            for pos, t in zip(("l", "c", "r"), texts):
                if not t:
                    continue
                s = _fmt(t, num, n, fname)
                w = text_width(s, chain, size)
                x = margin if pos == "l" else (R.width - w) / 2 if pos == "c" else R.width - margin - w
                y = margin + size * 0.8 if where == "header" else R.height - margin
                pt, d = _to_page(page, x, y)
                write_text(page, pt, s, chain, size, color, direction=d)
    pdf._text_cache.clear()


def page_numbers(pdf, pages, position="bottom-center", fmt="{p}", size=10, start=1, margin=28, color=(0, 0, 0)):
    v, h = position.split("-")
    slot = {"left": 0, "center": 1, "right": 2}[h]
    texts = ["", "", ""]
    texts[slot] = fmt
    spec = {"size": size, "margin": margin, "start": start, "color": color,
            "header": texts if v == "top" else ["", "", ""], "footer": texts if v == "bottom" else ["", "", ""]}
    header_footer(pdf, pages, spec)


# ----------------------------------------------------------------------------- 워터마크
def watermark_text(pdf, pages, text, size=60, color=(0.6, 0.6, 0.6), opacity=0.3, angle=45, tiled=False):
    import math
    pdf.snapshot()
    chain = _default_chain(bold=True)
    w = text_width(text, chain, size)
    for pno in pages:
        page = pdf.doc[pno]
        R = page.rect
        a = math.radians(angle)
        cos, sin = math.cos(a), -math.sin(a)  # 화면 좌표는 y 아래 방향
        centers = []
        if tiled:
            stepx, stepy = w * 0.9 + 80, size * 4
            y = stepy / 2
            row = 0
            while y < R.height + stepy:
                x = (stepx / 2) * (row % 2)
                while x < R.width + stepx:
                    centers.append(pymupdf.Point(x, y))
                    x += stepx
                y += stepy
                row += 1
        else:
            centers = [pymupdf.Point(R.width / 2, R.height / 2)]
        for c in centers:
            # 글자 가운데가 c 에 오도록 시작점 계산 (회전 고려)
            ox = c.x - (w / 2) * cos - (size * 0.35) * sin
            oy = c.y - (w / 2) * sin + (size * 0.35) * cos
            pt, (dx, dy) = _to_page(page, ox, oy, cos, sin)
            tw = pymupdf.TextWriter(page.rect)
            _append_chain(tw, pt, text, chain, size)
            tw.write_text(page, color=color, opacity=opacity, morph=(pt, pymupdf.Matrix(dx, -dy, dy, dx, 0, 0)))
    pdf._text_cache.clear()


def _append_chain(tw, pt, text, chain, size):
    used = {}
    runs, run, link = [], "", None
    plan = chain.plan(text)
    for ch in text:
        ln = chain.pick_in(ch, plan)
        if link is not None and ln is not link:
            runs.append((run, link))
            run = ""
        link = ln
        run += ch
    if run:
        runs.append((run, link))
    for r, ln in runs:
        used.setdefault(id(ln), set()).update(r)
    cur = pt
    for r, ln in runs:
        _, cur = tw.append(cur, r, font=ln.for_chars(used[id(ln)]), fontsize=size)


def watermark_image(pdf, pages, image_path, scale=0.5, opacity=0.3, position="center"):
    pdf.snapshot()
    img = Image.open(image_path).convert("RGBA")
    a = img.getchannel("A").point(lambda v: int(v * opacity))
    img.putalpha(a)
    bio = io.BytesIO()
    img.save(bio, "PNG")
    data = bio.getvalue()
    for pno in pages:
        page = pdf.doc[pno]
        R = page.rect
        w = R.width * scale
        h = w * img.height / img.width
        if position == "center":
            r = pymupdf.Rect((R.width - w) / 2, (R.height - h) / 2, (R.width + w) / 2, (R.height + h) / 2)
        elif position == "top-right":
            r = pymupdf.Rect(R.width - w - 30, 30, R.width - 30, 30 + h)
        else:  # bottom-right
            r = pymupdf.Rect(R.width - w - 30, R.height - h - 30, R.width - 30, R.height - 30)
        rr = r * page.derotation_matrix
        rr.normalize()
        page.insert_image(rr, stream=data, overlay=True, rotate=page.rotation)
    pdf._text_cache.clear()


# ----------------------------------------------------------------------------- 비교
def compare(doc_a: pymupdf.Document, doc_b: pymupdf.Document, name_a="A", name_b="B"):
    """페이지별 텍스트 비교 → (HTML 보고서, 변경 수)"""
    rows = []
    changes = 0
    n = max(len(doc_a), len(doc_b))
    for i in range(n):
        ta = doc_a[i].get_text("text", sort=True).splitlines() if i < len(doc_a) else []
        tb = doc_b[i].get_text("text", sort=True).splitlines() if i < len(doc_b) else []
        sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
        page_rows = []
        for op, a0, a1, b0, b1 in sm.get_opcodes():
            if op == "equal":
                continue
            changes += 1
            left = "<br>".join(_inline_diff(ta[a0:a1], tb[b0:b1], "del"))
            right = "<br>".join(_inline_diff(tb[b0:b1], ta[a0:a1], "ins"))
            label = {"replace": "변경", "delete": "삭제", "insert": "추가"}[op]
            page_rows.append(f"<tr><td class=k>{label}</td><td>{left}</td><td>{right}</td></tr>")
        if page_rows:
            rows.append(f"<tr><th colspan=3>{i + 1} 페이지</th></tr>" + "".join(page_rows))
    style = ("<style>table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:4px;"
             "vertical-align:top}th{background:#eef}td.k{width:40px;color:#555}"
             "del{background:#ffd6d6;text-decoration:line-through}ins{background:#d6ffd6;text-decoration:none}</style>")
    head = f"<tr><th></th><th>{html.escape(name_a)}</th><th>{html.escape(name_b)}</th></tr>"
    body = "".join(rows) if rows else "<tr><td colspan=3>차이가 없습니다.</td></tr>"
    return f"{style}<table>{head}{body}</table>", changes


def _inline_diff(lines, other, tag):
    a = "\n".join(lines)
    b = "\n".join(other)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for op, a0, a1, _b0, _b1 in sm.get_opcodes():
        seg = html.escape(a[a0:a1]).replace("\n", "<br>")
        if op == "equal":
            out.append(seg)
        elif seg:
            out.append(f"<{tag}>{seg}</{tag}>")
    return ["".join(out)]


# ----------------------------------------------------------------------------- 속성/책갈피/이미지
def get_metadata(doc):
    m = doc.metadata or {}
    return {k: m.get(k, "") or "" for k in ("title", "author", "subject", "keywords", "creator", "producer")}


def set_metadata(pdf, meta: dict):
    pdf.snapshot()
    m = dict(pdf.doc.metadata or {})
    m.update(meta)
    pdf.doc.set_metadata(m)


def set_toc(pdf, toc):
    pdf.snapshot()
    pdf.doc.set_toc(toc)


def extract_images(doc, out_dir, min_size=32) -> int:
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    seen = set()
    for pno in range(len(doc)):
        for img in doc[pno].get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            if info["width"] < min_size or info["height"] < min_size:
                continue
            n += 1
            ext = info.get("ext", "png")
            if info.get("smask"):
                pix = pymupdf.Pixmap(doc, xref)
                try:
                    pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, info["smask"]))
                except Exception:
                    pass
                if pix.colorspace and pix.colorspace.n > 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                pix.save(os.path.join(out_dir, f"p{pno + 1:03d}_{n:03d}.png"))
            else:
                with open(os.path.join(out_dir, f"p{pno + 1:03d}_{n:03d}.{ext}"), "wb") as f:
                    f.write(info["image"])
    return n


# ----------------------------------------------------------------------------- 도장/서명
STAMPS = ["승인", "검토", "반려", "기밀", "사본", "완료", "긴급", "확인", "APPROVED", "DRAFT"]


def _font_path(bold=True):
    cands = []
    windir = os.environ.get("WINDIR", r"C:\Windows")
    cands += [os.path.join(windir, "Fonts", "malgunbd.ttf" if bold else "malgun.ttf")]
    sf = fontmgr.SYSTEM_FONTS.find("malgungothicbold" if bold else "malgungothic") or \
        fontmgr.SYSTEM_FONTS.find("nanumgothicbold" if bold else "nanumgothic")
    if sf and not sf.path.lower().endswith((".ttc", ".otc")):
        cands.append(sf.path)
    cands += ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def stamp_image(text: str, color=(220, 30, 30), date=True) -> bytes:
    """빨간 테두리 도장 이미지(PNG, 투명 배경)."""
    fp = _font_path(True)
    S = 4
    font = ImageFont.truetype(fp, 64 * S) if fp else ImageFont.load_default()
    small = ImageFont.truetype(fp, 22 * S) if fp else ImageFont.load_default()
    d0 = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tb = d0.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    sub = datetime.date.today().strftime("%Y.%m.%d") if date else ""
    sb = d0.textbbox((0, 0), sub, font=small) if sub else (0, 0, 0, 0)
    W = max(tw, sb[2] - sb[0]) + 60 * S
    H = th + (sb[3] - sb[1] + 14 * S if sub else 0) + 50 * S
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = tuple(color) + (235,)
    d.rounded_rectangle((6 * S, 6 * S, W - 6 * S, H - 6 * S), radius=18 * S, outline=col, width=7 * S)
    d.text(((W - tw) / 2 - tb[0], 22 * S - tb[1]), text, font=font, fill=col)
    if sub:
        d.text(((W - (sb[2] - sb[0])) / 2 - sb[0], 22 * S + th + 12 * S - sb[1]), sub, font=small, fill=col)
    im = im.resize((W // 2, H // 2), Image.LANCZOS)
    bio = io.BytesIO()
    im.save(bio, "PNG")
    return bio.getvalue()


def signatures_dir():
    d = os.path.join(fontmgr.cache_dir(), "signatures")
    os.makedirs(d, exist_ok=True)
    return d


def list_signatures():
    d = signatures_dir()
    return sorted((os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")),
                  key=os.path.getmtime, reverse=True)
