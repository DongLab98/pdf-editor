"""광고 배너.

광고 내용은 프로그램 밖의 설정 파일(ads.json) 하나로 관리합니다.
- assets/ads/config.json 의 "url" 에 ads.json 주소(예: GitHub Pages)를 적어 두면
  프로그램이 실행될 때 받아 와서 캐시에 저장합니다(3시간마다 갱신, 실패하면 캐시 사용).
- url 이 비어 있거나 인터넷이 안 되면 assets/ads/default.json 의 기본 광고를 보여 줍니다.
- 프로그램은 ads.json 과 배너 그림만 내려받을 뿐, 사용자 정보나 문서는 어디에도 보내지 않습니다.

ads.json 형식:
{
  "rotate_sec": 40,
  "ads": [
    {"id": "a1", "slots": ["home", "bar"], "image": "https://.../728x90.png",
     "image_bar": "https://.../468x60.png", "text": "그림이 없을 때 보일 글",
     "url": "https://클릭하면-열릴-주소", "note": "쿠팡 파트너스 활동의 일환으로 수수료를 받을 수 있음",
     "weight": 1, "start": "2026-11-01", "end": "2026-12-31"}
  ]
}
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import urllib.request
from datetime import date

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from . import fontmgr, theme

REFRESH_SEC = 3 * 3600
TIMEOUT = 6
MAX_IMAGE = 2 * 1024 * 1024
MAX_JSON = 256 * 1024
UA = "PdfEditorKR-ads"


def _ads_dir():
    return os.path.join(fontmgr.app_dir(), "assets", "ads")


def _cache():
    d = os.path.join(fontmgr.cache_dir(), "ads")
    os.makedirs(d, exist_ok=True)
    return d


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_web(u):
    # 보안: 암호화된 https 주소만 허용 (http 는 중간에서 광고를 바꿔치기할 수 있음)
    return isinstance(u, str) and u.lower().startswith("https://")


def _is_local_test(u):
    return isinstance(u, str) and u.lower().startswith(("http://127.0.0.1", "http://localhost"))


def _fetch(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("too large")
    return data


def config_url():
    env = os.environ.get("PDFEDITOR_ADS_URL")
    if env is not None:
        return env.strip()
    cfg = _read_json(os.path.join(_ads_dir(), "config.json")) or {}
    u = (cfg.get("url") or "").strip()
    return u if (_is_web(u) or _is_local_test(u)) else ""


class AdManager(QObject):
    """광고 목록을 불러오고(기본 → 캐시 → 인터넷) 바뀌면 알려 줍니다."""
    changed = Signal()
    _fetched = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rotate_sec = 40
        self.ads: list[dict] = []
        self.links: dict[str, str] = {}   # {"blog": 사용법 블로그, "download": 다운로드, "source": 소스 코드, "contact": 문의}
        self.pixmaps: dict[str, QPixmap] = {}
        self._fetched.connect(self._apply)
        d = _read_json(os.path.join(_ads_dir(), "default.json")) or {}
        self.default_links = {k: v for k, v in (d.get("links") or {}).items()
                              if isinstance(v, str) and (_is_web(v) or v.startswith("mailto:"))}
        self._load_local()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_SEC * 1000)
        QTimer.singleShot(1500, self.refresh)

    # ---------- 불러오기
    def _load_local(self):
        cached = _read_json(os.path.join(_cache(), "ads.json"))
        default = _read_json(os.path.join(_ads_dir(), "default.json")) or {}
        self._set(default, _ads_dir())
        if cached:
            self._set(cached, _cache())

    def link(self, key):
        """links 값. 인터넷에서 받은 것이 없으면 기본값(default.json)."""
        return self.links.get(key) or self.default_links.get(key)

    def _set(self, data, base, force=False) -> bool:
        if not isinstance(data, dict):
            return False
        ads = []
        today = date.today().isoformat()
        for a in data.get("ads") or []:
            if not isinstance(a, dict) or not (_is_web(a.get("url")) or str(a.get("url", "")).startswith("mailto:")):
                continue
            if a.get("start") and str(a["start"]) > today:
                continue
            if a.get("end") and str(a["end"]) < today:
                continue
            a = dict(a)
            for key in ("image", "image_bar"):
                p = a.get("_" + key) or a.get(key)
                if p and not _is_web(p):
                    p = os.path.join(base, os.path.basename(p))
                    a["_" + key] = p if os.path.exists(p) else None
            ads.append(a)
        try:
            self.rotate_sec = max(15, int(data.get("rotate_sec", 40)))
        except (TypeError, ValueError):
            self.rotate_sec = 40
        links = {}
        for k, v in (data.get("links") or {}).items() if isinstance(data.get("links"), dict) else []:
            if isinstance(v, str) and (_is_web(v) or v.startswith("mailto:")):
                links[str(k)] = v
        if links or force:
            self.links = links
        if not ads and self.ads and not force:
            self.changed.emit()
            return False
        self.ads = ads
        self.pixmaps.clear()
        self.changed.emit()
        return bool(ads)

    def refresh(self):
        url = config_url()
        if not url:
            return
        stamp = os.path.join(_cache(), "last_fetch")
        try:
            if time.time() - os.path.getmtime(stamp) < REFRESH_SEC and self.ads and \
                    os.path.exists(os.path.join(_cache(), "ads.json")):
                return
        except OSError:
            pass
        threading.Thread(target=self._worker, args=(url, stamp), daemon=True).start()

    def _worker(self, url, stamp):
        try:
            data = json.loads(_fetch(url, MAX_JSON).decode("utf-8-sig"))
            if not isinstance(data, dict):
                return
            cache = _cache()
            base = url.rsplit("/", 1)[0] + "/"
            for a in data.get("ads") or []:
                if not isinstance(a, dict):
                    continue
                for key in ("image", "image_bar"):
                    src = a.get(key)
                    if not src:
                        continue
                    if not _is_web(src):
                        if "://" in str(src):
                            continue          # http 등 암호화되지 않은 주소의 그림은 받지 않음
                        src = base + str(src).lstrip("./")
                    ext = os.path.splitext(src.split("?")[0])[1].lower()
                    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                        ext = ".img"
                    name = hashlib.sha1(src.encode()).hexdigest()[:16] + ext
                    path = os.path.join(cache, name)
                    if not os.path.exists(path):
                        try:
                            blob = _fetch(src, MAX_IMAGE)
                            with open(path + ".tmp", "wb") as f:
                                f.write(blob)
                            os.replace(path + ".tmp", path)
                        except Exception:
                            continue
                    a["_" + key] = name
            with open(os.path.join(cache, "ads.json.tmp"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(os.path.join(cache, "ads.json.tmp"), os.path.join(cache, "ads.json"))
            with open(stamp, "w") as f:
                f.write(str(time.time()))
            self._fetched.emit(data)
        except Exception:
            pass

    def _apply(self, data):
        self._set(data, _cache(), force=True)

    # ---------- 고르기
    def for_slot(self, slot):
        return [a for a in self.ads if slot in (a.get("slots") or ["home", "bar"])]

    def pick(self, slot, exclude=None):
        pool = self.for_slot(slot)
        if len(pool) > 1 and exclude is not None:
            pool = [a for a in pool if a is not exclude] or pool
        if not pool:
            return None
        weights = []
        for a in pool:
            try:
                weights.append(max(0.0, float(a.get("weight", 1))))
            except (TypeError, ValueError):
                weights.append(1.0)
        if sum(weights) <= 0:
            weights = [1.0] * len(pool)
        return random.choices(pool, weights)[0]

    def pixmap(self, ad, slot):
        key = "_image_bar" if slot == "bar" and ad.get("_image_bar") else "_image"
        p = ad.get(key)
        if not p:
            return None
        if not os.path.isabs(p):
            p = os.path.join(_cache(), p)
        if p not in self.pixmaps:
            pm = QPixmap(p)
            self.pixmaps[p] = pm if not pm.isNull() else None
        return self.pixmaps[p]


_MANAGER: AdManager | None = None


def manager() -> AdManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = AdManager()
    return _MANAGER


class AdBanner(QWidget):
    """배너 한 칸. slot="home"(시작 화면, 728×90) / "bar"(문서 아래 띠, 468×60)."""

    def __init__(self, slot, size: QSize, closable=False, parent=None):
        super().__init__(parent)
        self.slot = slot
        self.box = size
        self.ad = None
        self.mgr = manager()
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(size.height())
        self.setMinimumWidth(min(size.width(), 320))
        self.setMaximumWidth(size.width())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.close_btn = None
        if closable:
            b = QToolButton(self)
            b.setIcon(theme.icon("x", theme.INK_SOFT))
            b.setIconSize(QSize(12, 12))
            b.setFixedSize(18, 18)
            b.setAutoRaise(True)
            b.setToolTip("이번 실행 동안 광고 숨기기")
            b.setCursor(Qt.ArrowCursor)
            b.clicked.connect(self._dismiss)
            self.close_btn = b
        self._rot = QTimer(self)
        self._rot.timeout.connect(self.next_ad)
        self.mgr.changed.connect(self.next_ad)
        self.dismissed = False
        self.next_ad()

    def next_ad(self):
        self.ad = self.mgr.pick(self.slot, self.ad)
        self.setToolTip((self.ad or {}).get("note") or (self.ad or {}).get("text") or "")
        self.setVisible(self.ad is not None and not self.dismissed)
        self._rot.start(self.mgr.rotate_sec * 1000)
        self.update()

    def _dismiss(self):
        self.dismissed = True
        self.hide()
        if self.parentWidget() is not None and hasattr(self.parentWidget(), "ad_dismissed"):
            self.parentWidget().ad_dismissed()

    def resizeEvent(self, e):
        if self.close_btn:
            self.close_btn.move(self.width() - 20, 2)
        super().resizeEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.ad and self.rect().contains(e.position().toPoint()):
            QDesktopServices.openUrl(QUrl(self.ad["url"]))

    def paintEvent(self, e):
        if not self.ad:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.setClipPath(path)
        pm = self.mgr.pixmap(self.ad, self.slot)
        if pm:
            p.fillRect(r, QColor(self.ad.get("bg") or "#ffffff"))
            s = pm.size().scaled(self.size(), Qt.KeepAspectRatio)
            x = (self.width() - s.width()) / 2
            y = (self.height() - s.height()) / 2
            p.drawPixmap(QRectF(x, y, s.width(), s.height()), pm, QRectF(pm.rect()))
        else:
            p.fillRect(r, QColor(self.ad.get("bg") or theme.ACCENT_SOFT))
            p.setPen(QColor(self.ad.get("fg") or theme.INK))
            f = QFont(self.font())
            f.setPointSizeF(12 if self.slot == "home" else 10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(r.adjusted(16, 0, -60, 0), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                       self.ad.get("text") or self.ad["url"])
        p.setClipping(False)
        p.setPen(QColor(0, 0, 0, 30))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 6, 6)
        # "광고" 표시 (표시광고법·추천보증 심사지침 — 광고임을 알림)
        tag = "광고"
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(tag) + 8
        right = self.width() - (24 if self.close_btn else 4)
        tr = QRectF(right - tw, 4, tw, 13)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(tr, 3, 3)
        p.setPen(QColor("white"))
        p.drawText(tr, Qt.AlignCenter, tag)
        p.end()


class AdStrip(QWidget):
    """문서 화면 아래의 얇은 광고 띠 (가운데에 468×60 배너)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        self.setObjectName("AdStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.addStretch()
        self.banner = AdBanner("bar", QSize(468, 60), closable=True, parent=self)
        lay.addWidget(self.banner)
        lay.addStretch()

    def ad_dismissed(self):
        self.hide()
