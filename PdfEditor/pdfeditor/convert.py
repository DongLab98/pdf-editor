"""변환: PDF → Word/Excel/PowerPoint/이미지/텍스트, 이미지/텍스트/Office/HWP → PDF."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile

import pymupdf
from PIL import Image

from .fontmgr import build_chain, text_width, write_text


def _pages(doc, pages):
    return list(range(len(doc))) if pages is None else pages


# ----------------------------------------------------------------------------- PDF → 이미지/텍스트
def to_images(doc, out_dir, base, pages=None, dpi=150, fmt="png", progress=None):
    os.makedirs(out_dir, exist_ok=True)
    files = []
    pl = _pages(doc, pages)
    for i, p in enumerate(pl):
        pix = doc[p].get_pixmap(dpi=dpi, alpha=False)
        path = os.path.join(out_dir, f"{base}_{p + 1:03d}.{fmt}")
        if fmt in ("jpg", "jpeg"):
            pix.save(path, jpg_quality=90)
        else:
            pix.save(path)
        files.append(path)
        if progress and not progress(i + 1, len(pl)):
            break
    return files


def to_text(doc, out_path, pages=None):
    with open(out_path, "w", encoding="utf-8-sig") as f:
        for p in _pages(doc, pages):
            f.write(doc[p].get_text("text", sort=True))
            f.write("\n\f\n")


# ----------------------------------------------------------------------------- PDF → Word
def to_word(pdf_path_or_bytes, out_path, pages=None, password=None, progress=None):
    """pdf2docx 로 서식(글꼴, 표, 이미지, 단락)을 최대한 유지해 변환."""
    import logging
    logging.getLogger("pdf2docx").setLevel(logging.ERROR)
    from pdf2docx import Converter
    tmp = None
    if isinstance(pdf_path_or_bytes, (bytes, bytearray)):
        fd, tmp = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(pdf_path_or_bytes)
        src = tmp
    else:
        src = pdf_path_or_bytes
    try:
        cv = Converter(src, password=password)
        try:
            cv.convert(out_path, pages=pages, multi_processing=False)
        finally:
            cv.close()
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


# ----------------------------------------------------------------------------- PDF → Excel
def to_excel(doc, out_path, pages=None, progress=None):
    """페이지의 표를 엑셀 시트로. 표가 없는 페이지는 텍스트 줄을 칸으로 나눠 넣음."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="999999")
    pl = _pages(doc, pages)
    n_tables = 0
    for i, p in enumerate(pl):
        page = doc[p]
        try:
            tabs = page.find_tables().tables
        except Exception:
            tabs = []
        if tabs:
            for ti, t in enumerate(tabs, 1):
                ws = wb.create_sheet(f"p{p + 1}_표{ti}"[:31])
                for r, row in enumerate(t.extract(), 1):
                    for c, val in enumerate(row, 1):
                        cell = ws.cell(r, c, _num(val))
                        cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                        if r == 1:
                            cell.font = Font(bold=True)
                _autowidth(ws, get_column_letter)
                n_tables += 1
        else:
            ws = wb.create_sheet(f"p{p + 1}"[:31])
            grid = _layout_grid(page)
            for r, row in enumerate(grid, 1):
                for c, val in enumerate(row, 1):
                    if val:
                        ws.cell(r, c, _num(val))
            _autowidth(ws, get_column_letter)
        if progress and not progress(i + 1, len(pl)):
            break
    if not wb.sheetnames:
        wb.create_sheet("빈 문서")
    wb.save(out_path)
    return n_tables


def _layout_grid(page):
    """글자 위치로 행/열을 추정해 표 형태로 (표 선이 없는 문서용)."""
    d = page.get_text("rawdict")
    segs = []  # (y, x0, x1, text, size)
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            chars = [c for s in ln.get("spans", []) for c in s.get("chars", [])]
            size = max((s["size"] for s in ln.get("spans", [])), default=10)
            cur, last = [], None
            for c in chars:
                if last is not None and c["c"].strip() and c["bbox"][0] - last > size * 0.3:
                    segs.append(cur)
                    cur = []
                cur.append(c)
                if c["c"].strip():
                    last = c["bbox"][2]
            segs.append(cur)
    rows = []
    items = []
    for sg in segs:
        txt = "".join(c["c"] for c in sg).strip()
        if not txt:
            continue
        nz = [c for c in sg if c["c"].strip()]
        y = sum(c["origin"][1] for c in nz) / len(nz)
        items.append((y, nz[0]["bbox"][0], txt))
    if not items:
        return []
    items.sort()
    # 행: 기준선이 비슷한 것끼리
    for it in items:
        if rows and abs(rows[-1][0] - it[0]) < 3:
            rows[-1][1].append(it)
        else:
            rows.append([it[0], [it]])
    # 열: 시작 x 좌표 군집
    xs = sorted(it[1] for it in items)
    cols = []
    for x in xs:
        if not cols or x - cols[-1][-1] > 12:
            cols.append([x])
        else:
            cols[-1].append(x)
    centers = [sum(c) / len(c) for c in cols]

    def col_of(x):
        return min(range(len(centers)), key=lambda i: abs(centers[i] - x))
    grid = []
    for _y, its in rows:
        row = [""] * len(centers)
        for _yy, x, txt in sorted(its, key=lambda t: t[1]):
            k = col_of(x)
            row[k] = (row[k] + " " + txt).strip()
        grid.append(row)
    # 두 줄 이상에서 쓰이는 열만 진짜 열로 보고, 나머지는 왼쪽 칸에 붙임 (일반 문장 보호)
    use = [sum(1 for r in grid if r[k]) for k in range(len(centers))]
    strong = [k for k in range(len(centers)) if use[k] >= 2] or [0]
    out = []
    for r in grid:
        merged = {}
        last = None
        for k, v in enumerate(r):
            if not v:
                continue
            if k in strong or last is None:
                kk = k if k in strong else (max([s_ for s_ in strong if s_ <= k], default=strong[0]))
                merged[kk] = (merged.get(kk, "") + " " + v).strip()
                last = kk
            else:
                merged[last] = (merged[last] + " " + v).strip()
        row = [merged.get(k, "") for k in strong]
        while row and not row[-1]:
            row.pop()
        out.append(row)
    return out


def _num(v):
    if v is None:
        return ""
    s = str(v).strip()
    t = s.replace(",", "").replace("원", "").strip()
    try:
        if t and t.replace(".", "", 1).lstrip("-").isdigit():
            return float(t) if "." in t else int(t)
    except ValueError:
        pass
    return s


def _autowidth(ws, gl):
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                ln = max(len(x) for x in str(c.value).splitlines() or [""])
                ln = int(ln * 1.8) if any(ord(ch) > 0x1100 for ch in str(c.value)) else ln
                widths[c.column] = max(widths.get(c.column, 0), ln)
    for col, w in widths.items():
        ws.column_dimensions[gl(col)].width = min(60, max(8, w + 2))


# ----------------------------------------------------------------------------- PDF → PowerPoint
def to_ppt(doc, out_path, pages=None, dpi=150, progress=None):
    """각 페이지를 슬라이드 한 장으로 (보이는 그대로 이미지)."""
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    pl = _pages(doc, pages)
    if not pl:
        return
    r0 = doc[pl[0]].rect
    prs.slide_width = Emu(int(r0.width * 12700))
    prs.slide_height = Emu(int(r0.height * 12700))
    blank = prs.slide_layouts[6]
    for i, p in enumerate(pl):
        page = doc[p]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        bio = io.BytesIO(pix.tobytes("png"))
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(bio, 0, 0, width=prs.slide_width, height=prs.slide_height)
        notes = page.get_text("text", sort=True).strip()
        if notes:
            s.notes_slide.notes_text_frame.text = notes[:5000]
        if progress and not progress(i + 1, len(pl)):
            break
    prs.save(out_path)


# ----------------------------------------------------------------------------- → PDF
def images_to_pdf(paths, out_path, paper="fit", margin=0):
    doc = pymupdf.open()
    for p in paths:
        img = Image.open(p)
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode not in ("RGB", "L"):
            bg = Image.new("RGB", img.size, "white")
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                bg.paste(img, mask=img.getchannel("A"))
            img = bg
        bio = io.BytesIO()
        img.save(bio, "JPEG", quality=92) if img.width * img.height > 400000 else img.save(bio, "PNG")
        if paper == "fit":
            w, h = img.width * 72 / 96, img.height * 72 / 96
            page = doc.new_page(width=w + 2 * margin, height=h + 2 * margin)
            page.insert_image(pymupdf.Rect(margin, margin, margin + w, margin + h), stream=bio.getvalue())
        else:
            W, H = (595, 842)
            if img.width > img.height:
                W, H = H, W
            page = doc.new_page(width=W, height=H)
            m = margin or 20
            page.insert_image(pymupdf.Rect(m, m, W - m, H - m), stream=bio.getvalue(), keep_proportion=True)
    doc.save(out_path, garbage=3, deflate=True)
    return len(doc)


def text_to_pdf(txt_path, out_path, size=11):
    with open(txt_path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    chain = build_chain("MalgunGothic", 0, None)
    doc = pymupdf.open()
    W, H, M = 595, 842, 56
    lh = size * 1.6
    page, y = None, 0
    for para in text.replace("\r\n", "\n").split("\n"):
        lines = _wrap(para, chain, size, W - 2 * M) or [""]
        for ln in lines:
            if page is None or y + lh > H - M:
                page = doc.new_page(width=W, height=H)
                y = M
            if ln:
                write_text(page, (M, y + size), ln, chain, size)
            y += lh
    doc.subset_fonts()
    doc.save(out_path, garbage=3, deflate=True)


def _wrap(text, chain, size, width):
    out, cur = [], ""
    for ch in text:
        if text_width(cur + ch, chain, size) > width:
            # 영문 단어 중간이면 공백 기준으로 자르기
            if " " in cur and ch != " " and not ('\uac00' <= ch <= '\ud7a3'):
                k = cur.rfind(" ")
                out.append(cur[:k])
                cur = cur[k + 1:] + ch
            else:
                out.append(cur)
                cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


OFFICE_EXTS = {".doc": "word", ".docx": "word", ".rtf": "word", ".odt": "word",
               ".xls": "excel", ".xlsx": "excel", ".csv": "excel", ".ods": "excel",
               ".ppt": "ppt", ".pptx": "ppt", ".odp": "ppt",
               ".hwp": "hwp", ".hwpx": "hwp"}

_PS = {
    "word": r"""$a=New-Object -ComObject Word.Application;$a.Visible=$false;$a.DisplayAlerts=0;
try{$d=$a.Documents.Open('{src}',$false,$true);$d.ExportAsFixedFormat('{dst}',17);$d.Close($false)}finally{$a.Quit()}""",
    "excel": r"""$a=New-Object -ComObject Excel.Application;$a.Visible=$false;$a.DisplayAlerts=$false;
try{$w=$a.Workbooks.Open('{src}',0,$true);$w.ExportAsFixedFormat(0,'{dst}');$w.Close($false)}finally{$a.Quit()}""",
    "ppt": r"""$a=New-Object -ComObject PowerPoint.Application;
try{$p=$a.Presentations.Open('{src}',$true,$false,$false);$p.SaveAs('{dst}',32);$p.Close()}finally{$a.Quit()}""",
    "hwp": r"""$h=New-Object -ComObject HWPFrame.HwpObject;
try{try{$h.RegisterModule('FilePathCheckDLL','FilePathCheckerModule')|Out-Null}catch{};
$h.XHwpWindows.Item(0).Visible=$false;$h.Open('{src}','','forceopen:true')|Out-Null;
$h.SaveAs('{dst}','PDF','')|Out-Null}finally{$h.Quit()}""",
}


def office_to_pdf(src, out_path, timeout=300):
    """MS Office / 한컴오피스(한글)가 설치되어 있으면 그 프로그램으로 PDF 변환.
    없으면 LibreOffice 로 시도."""
    ext = os.path.splitext(src)[1].lower()
    kind = OFFICE_EXTS.get(ext)
    if not kind:
        raise ValueError("지원하지 않는 파일 형식입니다")
    errors = []
    if sys.platform.startswith("win"):
        script = _PS[kind].replace("{src}", os.path.abspath(src).replace("'", "''")) \
                          .replace("{dst}", os.path.abspath(out_path).replace("'", "''"))
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-Command", script], capture_output=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                return "office"
            errors.append((r.stderr or b"").decode("cp949", "ignore")[-300:])
        except Exception as e:
            errors.append(str(e))
    soffice = _find_soffice()
    if soffice:
        outdir = tempfile.mkdtemp()
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, src],
                           capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            produced = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
            if os.path.exists(produced):
                shutil.move(produced, out_path)
                return "libreoffice"
        finally:
            shutil.rmtree(outdir, ignore_errors=True)
    prog = {"word": "Microsoft Word", "excel": "Microsoft Excel", "ppt": "Microsoft PowerPoint",
            "hwp": "한컴오피스 한글"}[kind]
    raise RuntimeError(f"{prog} (또는 LibreOffice)가 설치되어 있어야 변환할 수 있습니다."
                       + (f"\n\n상세: {errors[-1].strip()}" if errors and errors[-1].strip() else ""))


def _find_soffice():
    for name in ("soffice", "soffice.exe"):
        p = shutil.which(name)
        if p:
            return p
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        p = os.path.join(base or "", "LibreOffice", "program", "soffice.exe")
        if base and os.path.exists(p):
            return p
    return None
