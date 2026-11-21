"""글꼴 관리: 원본 글꼴을 최대한 그대로 쓰기 위한 로직.

우선순위
 1) PDF 이름과 같은 글꼴이 PC(시스템)에 설치되어 있으면 그 글꼴 (모든 글자 사용 가능, 원본과 동일 디자인)
 2) PDF 안에 내장된(서브셋) 원본 글꼴 - 문서에 이미 쓰인 글자는 원본 그대로 재사용
 3) 원본 스타일(고딕/명조/굵게)에 맞춘 대체 글꼴 (맑은 고딕, 바탕 등)
 4) PyMuPDF 내장 CJK 글꼴 (최후의 수단)
글자 단위로 위 순서대로 '그 글자를 가진 첫 번째 글꼴'을 고르기 때문에
영문은 원본 글꼴, 한글만 대체 글꼴 같은 혼합도 자연스럽게 처리됩니다.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass, field

import pymupdf
from fontTools.ttLib import TTFont, TTCollection, newTable
from fontTools.ttLib.tables._c_m_a_p import cmap_format_4, cmap_format_12

logging.getLogger("fontTools").setLevel(logging.ERROR)

FONT_EXTS = (".ttf", ".otf", ".ttc", ".otc")

# PDF 표준 14 글꼴 -> PyMuPDF 내장 이름
BASE14 = [
    ("courier", {"": "cour", "b": "cobo", "i": "coit", "bi": "cobi"}),
    ("times", {"": "tiro", "b": "tibo", "i": "tiit", "bi": "tibi"}),
    ("helvetica", {"": "helv", "b": "hebo", "i": "heit", "bi": "hebi"}),
    ("arial", {"": "helv", "b": "hebo", "i": "heit", "bi": "hebi"}),
    ("symbol", {"": "symb"}),
    ("zapfdingbats", {"": "zadb"}),
]

# 스타일별 대체 글꼴 후보 (정규화된 이름). 앞에 있을수록 우선.
FALLBACKS = {
    "sans": ["malgungothic", "맑은고딕", "nanumgothic", "notosanscjkkr", "notosanskr",
             "applesdgothicneo", "gulim", "dotum", "arial", "dejavusans"],
    "sans_bold": ["malgungothicbold", "맑은고딕bold", "nanumgothicbold", "notosanscjkkrbold",
                  "notosanskrbold", "arialbold", "dejavusansbold"],
    "serif": ["batang", "바탕", "nanummyeongjo", "notoserifcjkkr", "notoserifkr",
              "applemyungjo", "timesnewroman", "dejavuserif"],
    "serif_bold": ["nanummyeongjobold", "notoserifcjkkrbold", "notoserifkrbold",
                   "batang", "timesnewromanbold", "dejavuserifbold"],
    "mono": ["gulimche", "dotumche", "d2coding", "nanumgothiccoding", "consolas",
             "couriernew", "dejavusansmono"],
}


# ----------------------------------------------------------------------------
# 이름 정규화
# ----------------------------------------------------------------------------
_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")


def decode_pdf_name(name: str) -> str:
    """PDF 글꼴 이름의 #XX 이스케이프 / CP949 깨짐을 복원 (예: 맑은고딕)."""
    if not name:
        return ""
    name = _SUBSET_RE.sub("", name)
    if "#" in name:
        try:
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]),
                         name.encode("latin-1", "ignore"))
            name = raw.decode("cp949")
        except Exception:
            pass
    # latin-1 로 잘못 읽힌 CP949 바이트 복원
    if any(0x80 <= ord(c) <= 0xFF for c in name) and all(ord(c) <= 0xFF for c in name):
        try:
            name = name.encode("latin-1").decode("cp949")
        except Exception:
            pass
    return name


def norm(name: str) -> str:
    n = decode_pdf_name(name).lower()
    n = "".join(c for c in n if c.isalnum())
    changed = True
    while changed:
        changed = False
        for suf in ("regular", "mt", "ps", "std", "normal", "book"):
            if n.endswith(suf) and len(n) > len(suf) + 2:
                n = n[: -len(suf)]
                changed = True
    return n


def style_of(fontname: str, flags: int = 0):
    """(bold, italic, serif, mono) 추정."""
    n = decode_pdf_name(fontname).lower()
    bold = bool(flags & 16) or any(k in n for k in ("bold", "black", "heavy", "semibold", "extrabold", ",bd", "-bd", "굵은")) \
        or n.endswith("bd") or n.endswith("b")
    italic = bool(flags & 2) or "italic" in n or "oblique" in n
    serif_words = ("batang", "myeongjo", "myungjo", "명조", "바탕", "times", "serif", "gungsuh", "궁서", "batan", "hy신명조",
                   "smmyeongjo", "garamond", "georgia", "cambria", "minion", "song", "mincho")
    serif = (bool(flags & 4) or any(k in n for k in serif_words)) and "sans" not in n
    mono = bool(flags & 8) or any(k in n for k in ("mono", "courier", "consol", "che", "coding"))
    return bold, italic, serif, mono


# ----------------------------------------------------------------------------
# 시스템 글꼴 색인
# ----------------------------------------------------------------------------
def system_font_dirs():
    dirs = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(windir, "Fonts"))
        la = os.environ.get("LOCALAPPDATA")
        if la:
            dirs.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts")]
    # 앱과 함께 배포한 글꼴 폴더
    dirs.append(os.path.join(app_dir(), "fonts"))
    return [d for d in dirs if os.path.isdir(d)]


def app_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cache_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "PdfEditorKR")
    else:
        d = os.path.join(os.path.expanduser("~"), ".cache", "pdfeditorkr")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class SysFont:
    path: str
    index: int
    family: str          # 표시용 이름
    full: str
    bold: bool = False
    italic: bool = False


class SystemFontIndex:
    VERSION = 4

    def __init__(self):
        self.fonts: list[SysFont] = []
        self.by_key: dict[str, int] = {}
        self.ready = threading.Event()
        self._lock = threading.Lock()

    # -- 색인 생성 (백그라운드) --
    def build_async(self):
        t = threading.Thread(target=self._build, daemon=True)
        t.start()

    def _list_files(self):
        files = []
        for d in system_font_dirs():
            for root, _dirs, names in os.walk(d):
                for n in names:
                    if n.lower().endswith(FONT_EXTS):
                        p = os.path.join(root, n)
                        try:
                            st = os.stat(p)
                            files.append((p, int(st.st_mtime), st.st_size))
                        except OSError:
                            pass
        return files

    def _build(self):
        try:
            files = self._list_files()
            cache_path = os.path.join(cache_dir(), "fontindex.json")
            cache = {}
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("v") == self.VERSION:
                    cache = data.get("files", {})
            except Exception:
                pass
            new_cache = {}
            fonts = []
            for path, mtime, size in files:
                key = f"{path}|{mtime}|{size}"
                entries = cache.get(key)
                if entries is None:
                    entries = self._read_names(path)
                new_cache[key] = entries
                for e in entries:
                    fonts.append(SysFont(path, e["i"], e["family"], e["full"], e["bold"], e["italic"]))
                    fonts[-1]._keys = e["keys"]  # type: ignore[attr-defined]
                    fonts[-1]._keys2 = e.get("keys2", [])  # type: ignore[attr-defined]
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"v": self.VERSION, "files": new_cache}, f, ensure_ascii=False)
            except Exception:
                pass
            by_key = {}
            # 정확한 이름(전체 이름/PostScript 이름)을 조합 이름보다 우선
            for attr in ("_keys", "_keys2"):
                for i, sf in enumerate(fonts):
                    for k in getattr(sf, attr):
                        by_key.setdefault(k, i)
            with self._lock:
                self.fonts = fonts
                self.by_key = by_key
        finally:
            self.ready.set()

    @staticmethod
    def _read_names(path):
        out = []
        try:
            if path.lower().endswith((".ttc", ".otc")):
                coll = TTCollection(path, lazy=True)
                fonts = list(coll.fonts)
            else:
                fonts = [TTFont(path, lazy=True, fontNumber=0)]
        except Exception:
            return out
        for i, tt in enumerate(fonts):
            try:
                name = tt["name"]
                keys = set()
                fam_en = full_en = None
                fam_ko = None
                sub_en = ""
                for rec in name.names:
                    if rec.nameID not in (1, 2, 4, 6, 16, 17):
                        continue
                    try:
                        s = rec.toUnicode()
                    except Exception:
                        continue
                    if rec.nameID in (4, 6):
                        keys.add(norm(s))
                    if rec.nameID in (1, 16):
                        if rec.langID in (0x412,):
                            fam_ko = fam_ko or s
                        elif rec.langID in (0x409, 0) and rec.nameID == 1:
                            fam_en = s
                    if rec.nameID in (2, 17) and rec.langID in (0x409, 0):
                        sub_en = s
                    if rec.nameID == 4 and rec.langID in (0x409, 0):
                        full_en = s
                # family + subfamily 조합 키 (ID1+ID2, ID16+ID17 끼리만 짝지음)
                keys2 = set()
                byid = {}
                for rec in name.names:
                    try:
                        byid.setdefault(rec.nameID, set()).add(rec.toUnicode())
                    except Exception:
                        pass
                for fid, sid in ((1, 2), (16, 17)):
                    for fm in byid.get(fid, ()):
                        subs = byid.get(sid, set())
                        for sb in subs:
                            keys2.add(norm(fm + sb))
                        if not subs or any(x.lower() in ("regular", "normal", "보통", "표준") for x in subs):
                            keys2.add(norm(fm))
                keys2 -= keys
                keys.discard("")
                fsel = 0
                try:
                    fsel = tt["OS/2"].fsSelection
                except Exception:
                    pass
                bold = bool(fsel & 0x20) or "bold" in sub_en.lower()
                italic = bool(fsel & 0x01) or "italic" in sub_en.lower()
                fam = fam_ko or fam_en or os.path.basename(path)
                full = full_en or fam
                if fam_ko and sub_en and sub_en.lower() not in ("regular", "normal"):
                    disp = f"{fam_ko} {sub_en}"
                else:
                    disp = full if not fam_ko else fam_ko
                keys2.discard("")
                out.append({"i": i, "family": disp, "full": full, "bold": bold, "italic": italic,
                            "keys": sorted(keys), "keys2": sorted(keys2)})
            except Exception:
                continue
        return out

    # -- 조회 --
    def find(self, *names) -> SysFont | None:
        with self._lock:
            for n in names:
                i = self.by_key.get(norm(n))
                if i is not None:
                    return self.fonts[i]
        return None

    def display_list(self):
        with self._lock:
            seen = {}
            for sf in self.fonts:
                seen.setdefault(sf.family, sf)
            return sorted(seen.items(), key=lambda kv: kv[0].lower())


SYSTEM_FONTS = SystemFontIndex()

_font_cache: dict[tuple, pymupdf.Font] = {}


def load_sysfont(sf: SysFont) -> pymupdf.Font | None:
    key = (sf.path, sf.index)
    if key in _font_cache:
        return _font_cache[key]
    try:
        if sf.path.lower().endswith((".ttc", ".otc")):
            tt = TTFont(sf.path, fontNumber=sf.index)
            bio = io.BytesIO()
            tt.save(bio)
            f = pymupdf.Font(fontbuffer=bio.getvalue())
        else:
            f = pymupdf.Font(fontfile=sf.path)
    except Exception:
        f = None
    _font_cache[key] = f
    return f


# ----------------------------------------------------------------------------
# 내장(서브셋) 글꼴 복원
# ----------------------------------------------------------------------------
class EmbeddedFonts:
    """문서에 내장된 서브셋 글꼴에 cmap 을 다시 만들어 재사용 가능하게 한다."""

    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self.cache: dict[str, pymupdf.Font | None] = {}
        self.char_maps: dict[str, dict[int, int]] | None = None
        self.xrefs: dict[str, int] = {}

    def invalidate(self, doc):
        self.doc = doc
        self.cache.clear()
        self.char_maps = None
        self.xrefs.clear()

    def _scan(self):
        self.char_maps = {}
        doc = self.doc
        for pno in range(min(len(doc), 60)):
            page = doc[pno]
            try:
                for f in page.get_fonts(full=True):
                    nm = _SUBSET_RE.sub("", f[3])
                    self.xrefs.setdefault(nm, f[0])
                for s in page.get_texttrace():
                    m = self.char_maps.setdefault(s["font"], {})
                    for ch in s["chars"]:
                        if ch[0] > 31 and ch[1] >= 0:
                            m.setdefault(ch[0], ch[1])
            except Exception:
                continue

    def get(self, span_font: str) -> pymupdf.Font | None:
        if span_font in self.cache:
            return self.cache[span_font]
        if self.char_maps is None:
            self._scan()
        font = None
        try:
            xref = self.xrefs.get(span_font)
            if xref is None:  # 이름 표기 차이 보정
                for k, v in self.xrefs.items():
                    if norm(k) == norm(span_font):
                        xref = v
                        break
            if xref:
                _n, ext, _t, buf = self.doc.extract_font(xref)
                if buf and ext in ("ttf", "otf"):
                    font = self._rebuild(buf, self.char_maps.get(span_font, {}))
        except Exception:
            font = None
        self.cache[span_font] = font
        return font

    @staticmethod
    def _rebuild(buf: bytes, umap: dict[int, int]) -> pymupdf.Font | None:
        f0 = pymupdf.Font(fontbuffer=buf)
        # 이미 정상 cmap 이 있으면 그대로 사용
        test = [u for u in list(umap)[:20]]
        if test and all(f0.has_glyph(u) for u in test):
            return f0
        if not umap:
            return None
        tt = TTFont(io.BytesIO(buf))
        order = tt.getGlyphOrder()
        mapping = {u: order[g] for u, g in umap.items() if 0 <= g < len(order)}
        if not mapping:
            return None
        cm = newTable("cmap")
        cm.tableVersion = 0
        s4 = cmap_format_4(4)
        s4.platformID, s4.platEncID, s4.language = 3, 1, 0
        s4.cmap = {u: g for u, g in mapping.items() if u < 0x10000}
        tables = [s4]
        if any(u >= 0x10000 for u in mapping):
            s12 = cmap_format_12(12)
            s12.platformID, s12.platEncID, s12.format, s12.reserved = 3, 10, 12, 0
            s12.length = s12.language = s12.nGroups = 0
            s12.cmap = mapping
            tables.append(s12)
        cm.tables = tables
        tt["cmap"] = cm
        if "post" not in tt:
            post = newTable("post")
            post.formatType = 3.0
            post.italicAngle = post.underlinePosition = post.underlineThickness = 0
            post.isFixedPitch = post.minMemType42 = post.maxMemType42 = 0
            post.minMemType1 = post.maxMemType1 = 0
            tt["post"] = post
        out = io.BytesIO()
        tt.save(out)
        return pymupdf.Font(fontbuffer=out.getvalue())


# ----------------------------------------------------------------------------
# 글꼴 체인
# ----------------------------------------------------------------------------
def _script(ch: str) -> str:
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
        return "ko"
    if ch.isalpha() and (o < 0x250 or 0x1E00 <= o <= 0x1EFF):
        return "lat"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
        return "han"
    if 0x3040 <= o <= 0x30FF:
        return "ja"
    if 0x370 <= o <= 0x3FF or 0x400 <= o <= 0x4FF:
        return "grk"
    if ch.isdigit() or (o < 0x80):
        return "com"
    return "oth"


@dataclass
class FontLink:
    label: str
    font: pymupdf.Font
    kind: str  # system / embedded / base14 / fallback / user
    sysfont: SysFont | None = None

    def for_chars(self, chars: set[str]) -> pymupdf.Font:
        """PC 글꼴은 쓰인 글자만 남긴 서브셋을 만들어 넣음 (파일 크기 최소화)."""
        if self.sysfont is None:
            return self.font
        return subset_sysfont(self.sysfont, chars) or self.font


_subset_cache: dict = {}


def _ink(font: pymupdf.Font, text: str) -> int:
    d = pymupdf.open()
    p = d.new_page(width=40 * len(text) + 20, height=60)
    tw = pymupdf.TextWriter(p.rect)
    tw.append((10, 42), text, font=font, fontsize=30)
    tw.write_text(p)
    d2 = pymupdf.open("pdf", d.tobytes())
    pix = d2[0].get_pixmap(dpi=36, colorspace=pymupdf.csGRAY)
    return sum(1 for v in pix.samples if v < 128)


def _renders(font: pymupdf.Font, chars: set[str]) -> bool:
    """서브셋 글꼴이 실제로 그려지는지 확인 (깨진 서브셋 방지)."""
    sample = "".join(c for c in list(chars) if not c.isspace())[:6]
    if not sample:
        return True
    try:
        return _ink(font, sample) > 0
    except Exception:
        return False


def subset_sysfont(sf: SysFont, chars: set[str]) -> pymupdf.Font | None:
    key = (sf.path, sf.index, frozenset(chars))
    if key in _subset_cache:
        return _subset_cache[key]
    font = None
    try:
        from fontTools import subset as ftsubset
        tt = TTFont(sf.path, fontNumber=sf.index, lazy=False)
        opts = ftsubset.Options()
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.name_languages = ["*"]
        opts.notdef_outline = True
        opts.recalc_bounds = True
        opts.drop_tables += ["DSIG"]
        if "CFF " in tt:
            # CID 방식 CFF 는 글리프 번호가 바뀌면 깨지므로 번호 유지
            opts.retain_gids = True
        sub = ftsubset.Subsetter(opts)
        sub.populate(unicodes=[ord(c) for c in chars] + [0x20])
        sub.subset(tt)
        bio = io.BytesIO()
        tt.save(bio)
        font = pymupdf.Font(fontbuffer=bio.getvalue())
        if not _renders(font, chars):
            font = None
    except Exception:
        font = None
    if len(_subset_cache) > 200:
        _subset_cache.clear()
    _subset_cache[key] = font
    return font


@dataclass
class FontChain:
    links: list[FontLink] = field(default_factory=list)

    def pick(self, ch: str) -> FontLink:
        cp = ord(ch)
        for ln in self.links:
            if ln.font.has_glyph(cp):
                return ln
        # 공백류 등은 첫 글꼴로
        return self.links[0]

    def plan(self, text: str) -> dict:
        """문자 종류(한글/라틴/한자/숫자·기호…)별로, 그 종류의 글자를 '모두' 가진 첫 글꼴을 고름.
        → 원본 서브셋 글꼴에 없는 글자가 섞여도 한 단어 안에서 글꼴이 들쭉날쭉하지 않음."""
        groups: dict[str, set] = {}
        for ch in text:
            if not ch.isspace():
                groups.setdefault(_script(ch), set()).add(ord(ch))
        out = {}
        for cls, cps in groups.items():
            for ln in self.links:
                if all(ln.font.has_glyph(c) for c in cps):
                    out[cls] = ln
                    break
        return out

    def pick_in(self, ch: str, plan: dict) -> FontLink:
        ln = plan.get(_script(ch))
        if ln is not None and ln.font.has_glyph(ord(ch)):
            return ln
        return self.pick(ch)

    def describe(self, text: str) -> str:
        if not self.links:
            return "-"
        used = []
        plan = self.plan(text)
        for ch in text:
            if ch in "\n\r" or ch.isspace():
                continue
            ln = self.pick_in(ch, plan)
            if ln not in used:
                used.append(ln)
        if not used:
            used = [self.links[0]]
        kinds = {"system": "PC에 설치된 원본 글꼴", "embedded": "PDF 내장 원본 글꼴",
                 "base14": "PDF 표준 글꼴", "fallback": "대체 글꼴", "user": "선택한 글꼴"}
        return " + ".join(f"{u.label} ({kinds.get(u.kind, u.kind)})" for u in used)


def _fallback_links(bold, serif, mono) -> list[FontLink]:
    links = []
    keys = []
    if mono:
        keys += FALLBACKS["mono"]
    if serif:
        keys += FALLBACKS["serif_bold"] if bold else []
        keys += FALLBACKS["serif"]
    keys += FALLBACKS["sans_bold"] if bold else []
    keys += FALLBACKS["sans"]
    seen = set()
    for k in keys:
        sf = SYSTEM_FONTS.find(k)
        if sf and (sf.path, sf.index) not in seen:
            f = load_sysfont(sf)
            if f is not None:
                seen.add((sf.path, sf.index))
                links.append(FontLink(sf.family, f, "fallback", sf))
        if len(links) >= 3:
            break
    try:
        links.append(FontLink("Droid Sans Fallback", pymupdf.Font("cjk"), "fallback"))
    except Exception:
        links.append(FontLink("Helvetica", pymupdf.Font("helv"), "fallback"))
    return links


def base14_for(name: str, bold: bool, italic: bool):
    n = norm(name)
    for key, variants in BASE14:
        if key in n:
            v = ("b" if bold else "") + ("i" if italic else "")
            code = variants.get(v) or variants[""]
            return pymupdf.Font(code)
    return None


def build_chain(span_font: str, flags: int, embedded: EmbeddedFonts | None,
                override: SysFont | None = None) -> FontChain:
    bold, italic, serif, mono = style_of(span_font, flags)
    links: list[FontLink] = []
    if override is not None:
        f = load_sysfont(override)
        if f:
            links.append(FontLink(override.family, f, "user", override))
    else:
        clean = decode_pdf_name(span_font)
        sf = SYSTEM_FONTS.find(clean)
        if sf is None:
            # "Arial,Bold" / "Malgun Gothic Bold" 처럼 구분자 차이
            sf = SYSTEM_FONTS.find(clean.replace(",", "").replace("-", ""))
        if sf:
            f = load_sysfont(sf)
            if f:
                links.append(FontLink(sf.family, f, "system", sf))
        if embedded is not None:
            ef = embedded.get(span_font)
            if ef is not None:
                links.append(FontLink(clean, ef, "embedded"))
        b14 = base14_for(clean, bold, italic)
        if b14 is not None and not links:
            links.append(FontLink(clean, b14, "base14"))
    links += _fallback_links(bold, serif, mono)
    return FontChain(links)


def _plan_runs(lines, chain):
    plan, used = [], {}
    sp = chain.plan("".join(lines))
    for line in lines:
        runs, run, run_link = [], "", None
        for ch in line:
            ln = chain.pick_in(ch, sp) if not ch.isspace() else (run_link or chain.pick(ch))
            if run_link is not None and ln is not run_link:
                runs.append((run, run_link))
                run = ""
            run_link = ln
            run += ch
        if run and run_link is not None:
            runs.append((run, run_link))
        for r, ln in runs:
            used.setdefault(id(ln), set()).update(r)
        plan.append(runs)
    fonts = {id(ln): ln.for_chars(used[id(ln)]) for ln in chain.links if id(ln) in used}
    return plan, fonts


def write_block(page: pymupdf.Page, origin, lines: list[str], chain: FontChain, size: float, color=(0, 0, 0),
                direction=(1.0, 0.0), pitch: float | None = None, x_offsets=None, synth_bold=False,
                synth_italic=False, underline=False, render_mode=0, justify_width=None, opacity=None):
    """여러 줄을 글자별 글꼴로 씀. 정렬(x_offsets), 양쪽 맞춤, 가짜 굵게(외곽선)/기울임, 밑줄 지원."""
    pitch = pitch or size * 1.25
    cos, sin = direction
    ox, oy = origin
    plan, fonts = _plan_runs(lines, chain)
    tw = pymupdf.TextWriter(page.rect)
    ulines = []
    for li, runs in enumerate(plan):
        x0 = (x_offsets[li] if x_offsets and li < len(x_offsets) else 0.0)
        y = oy + li * pitch
        extra = 0.0
        by_space = False
        text = "".join(r for r, _ in runs)
        if justify_width and li < len(plan) - 1 and len(text.strip()) > 1:
            w = sum(fonts.get(id(ln), ln.font).text_length(r, fontsize=size) for r, ln in runs)
            slack = justify_width - x0 - w
            if 0 < slack < justify_width * 0.12:
                body = text.rstrip()
                nsp = body.strip().count(" ")
                # 단어 사이 공백을 늘리고, 공백이 없으면 글자 사이를 늘림
                extra = slack / nsp if nsp else slack / max(1, len(body) - 1)
                by_space = nsp > 0
        cur = pymupdf.Point(ox + x0, y)
        for r, ln in runs:
            f = fonts.get(id(ln), ln.font)
            if extra:
                for ch in r:
                    _, cur = tw.append(cur, ch, font=f, fontsize=size)
                    if not by_space or ch == " ":
                        cur = pymupdf.Point(cur.x + extra, cur.y)
            else:
                _, cur = tw.append(cur, r, font=f, fontsize=size)
        ulines.append((ox + x0, cur.x - (0 if by_space else extra), y))
    rotated = abs(cos - 1.0) > 1e-3 or abs(sin) > 1e-3
    M = pymupdf.Matrix(1, 0, 0.21, 1, 0, 0) if synth_italic else pymupdf.Matrix(1, 0, 0, 1, 0, 0)
    if rotated:
        M = M * pymupdf.Matrix(cos, -sin, sin, cos, 0, 0)  # 방향 (cos, sin) 으로 회전
    morph = (pymupdf.Point(ox, oy), M) if (synth_italic or rotated) else None
    kw = {"color": color, "morph": morph, "render_mode": 2 if synth_bold and render_mode == 0 else render_mode}
    if opacity is not None:
        kw["opacity"] = opacity
    tw.write_text(page, **kw)
    if underline:
        for x1, x2, y in ulines:
            if x2 - x1 < 0.5:
                continue
            pts = []
            for x in (x1, x2):
                dx, dy = x - ox, (y + size * 0.13) - oy
                pts.append(pymupdf.Point(ox + dx * cos - dy * sin, oy + dx * sin + dy * cos))
            page.draw_line(pts[0], pts[1], color=color, width=max(0.5, size * 0.06))
    return tw.text_rect


def write_text(page: pymupdf.Page, origin, text: str, chain: FontChain, size: float,
               color=(0, 0, 0), direction=(1.0, 0.0), render_mode=0, line_gap=1.25):
    """글자마다 알맞은 글꼴을 골라 씀. 여러 줄(\n) 지원."""
    return write_block(page, origin, text.split("\n"), chain, size, color, direction, size * line_gap,
                       render_mode=render_mode)


# ----------------------------------------------------------------------------- 굵게/기울임 변형
_STYLE_WORDS = ("bolditalic", "boldoblique", "extrabold", "semibold", "demibold", "bold", "italic", "oblique",
                "regular", "normal", "medium", "book", "roman", "bd", "굵게", "기울임", "보통")
_variant_index: dict | None = None


def family_key(name: str) -> str:
    n = norm(name)
    changed = True
    while changed:
        changed = False
        for w in _STYLE_WORDS:
            if n.endswith(w) and len(n) > len(w) + 2:
                n = n[: -len(w)]
                changed = True
    return n


def find_variant(name: str, bold: bool, italic: bool) -> SysFont | None:
    """같은 글꼴 가족에서 굵게/기울임 조합에 맞는 PC 글꼴 찾기 (예: 맑은 고딕 → 맑은 고딕 Bold)."""
    global _variant_index
    if not SYSTEM_FONTS.ready.is_set():
        return None
    if _variant_index is None:
        idx = {}
        for sf in SYSTEM_FONTS.fonts:
            for nm in {sf.full, sf.family}:
                idx.setdefault(family_key(nm), []).append(sf)
        _variant_index = idx
    key = family_key(decode_pdf_name(name))
    for sf in _variant_index.get(key, []):
        if sf.bold == bold and sf.italic == italic:
            return sf
    return None


def font_bytes(font: pymupdf.Font) -> bytes | None:
    try:
        b = font.buffer
        return bytes(b) if b else None
    except Exception:
        return None


def text_width(text: str, chain: FontChain, size: float, plan: dict | None = None) -> float:
    plan = chain.plan(text) if plan is None else plan
    w = 0.0
    for ch in text:
        w += chain.pick_in(ch, plan).font.text_length(ch, fontsize=size)
    return w