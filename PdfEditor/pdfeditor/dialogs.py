"""대화상자들."""
from __future__ import annotations

import pymupdf
from PIL import Image, ImageEnhance
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QCompleter, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import fontmgr
from .engine import PdfDocument, TextItem
from .fontmgr import build_chain, write_text


def to_qcolor(rgb):
    return QColor.fromRgbF(*[max(0.0, min(1.0, float(v))) for v in rgb])


def from_qcolor(c: QColor):
    return (c.redF(), c.greenF(), c.blueF())


class ColorButton(QPushButton):
    def __init__(self, rgb=(0, 0, 0), parent=None, compact=False):
        super().__init__(parent)
        self.compact = compact
        self.setFixedWidth(70)
        self.set_color(rgb)
        self.clicked.connect(self._pick)
        self.on_change = None

    def set_color(self, rgb):
        self.rgb = tuple(rgb)
        c = to_qcolor(self.rgb)
        fg = "#000" if c.lightness() > 128 else "#fff"
        self.setStyleSheet(f"background:{c.name()}; color:{fg}; border:1px solid #888; border-radius:3px; padding:3px")
        self.setText("가" if self.compact else c.name())

    def _pick(self):
        c = QColorDialog.getColor(to_qcolor(self.rgb), self, "색 선택")
        if c.isValid():
            self.set_color(from_qcolor(c))
            if self.on_change:
                self.on_change()


class TextDialog(QDialog):
    """텍스트 수정/추가 대화상자. 원본 글꼴 체인을 기본으로 사용."""

    def __init__(self, parent, pdf: PdfDocument, pno: int, item: TextItem | None,
                 style: TextItem | None = None, title="텍스트 수정"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 470)
        self.pdf, self.pno, self.item = pdf, pno, item
        self.style = item or style
        base = self.style

        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(item.text if item else "")
        self.edit.setFixedHeight(90)
        lay.addWidget(QLabel("내용 (Enter = 줄바꿈):"))
        lay.addWidget(self.edit)

        form = QFormLayout()
        self.font_combo = QComboBox()
        self.font_combo.setEditable(True)
        self.font_combo.setInsertPolicy(QComboBox.NoInsert)
        auto_name = fontmgr.decode_pdf_name(base.font) if base and not base.invisible else "맑은 고딕 계열"
        if item and item.invisible:
            self.font_combo.addItem("자동 — 스캔 문서용 대체 글꼴", ("auto", None))
        elif item:
            self.font_combo.addItem(f"자동 — 원본 글꼴 그대로 ({auto_name})", ("auto", None))
        elif base:
            self.font_combo.addItem(f"자동 — 주변 글꼴 ({auto_name})", ("auto", None))
        else:
            self.font_combo.addItem("자동 — 기본 글꼴", ("auto", None))
        seen = set()
        for it in pdf.text_items(pno, False):
            if it.invisible or it.font in seen:
                continue
            seen.add(it.font)
            self.font_combo.addItem(f"문서 글꼴: {fontmgr.decode_pdf_name(it.font)}", ("doc", it))
        for name, sf in fontmgr.SYSTEM_FONTS.display_list():
            self.font_combo.addItem(f"PC 글꼴: {name}", ("sys", sf))
        comp = QCompleter([self.font_combo.itemText(i) for i in range(self.font_combo.count())], self)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.font_combo.setCompleter(comp)
        form.addRow("글꼴:", self.font_combo)

        self.size = QDoubleSpinBox()
        self.size.setRange(2, 400)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        default_size = base.size if base else 11
        if item and item.invisible:
            default_size = max(4.0, item.bbox.height * 0.76)
        self.size.setValue(round(default_size, 1))
        form.addRow("크기:", self.size)

        bg, fg = (1, 1, 1), (0, 0, 0)
        if item and (item.invisible or item.on_image):
            bg, fg = pdf.sample_colors(pno, item.bbox)
        color = fg if (item and item.invisible) else (base.rgb if base else (0, 0, 0))
        self.color = ColorButton(color)
        form.addRow("글자색:", self.color)

        fill_row = QHBoxLayout()
        self.fill_chk = QCheckBox("배경색으로 원래 글자 덮기 (스캔/이미지 문서)")
        self.fill_chk.setChecked(bool(item and (item.invisible or item.on_image)))
        self.fill_color = ColorButton(bg)
        fill_row.addWidget(self.fill_chk)
        fill_row.addWidget(self.fill_color)
        fill_row.addStretch()
        fw = QWidget()
        fw.setLayout(fill_row)
        fill_row.setContentsMargins(0, 0, 0, 0)
        if item:
            form.addRow("배경:", fw)
        else:
            fw.hide()
        lay.addLayout(form)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#335; background:#eef3ff; padding:6px; border-radius:4px")
        lay.addWidget(self.info)
        lay.addWidget(QLabel("미리보기:"))
        self.preview = QLabel()
        self.preview.setMinimumHeight(90)
        self.preview.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.preview.setStyleSheet("background:white; border:1px solid #ccc")
        lay.addWidget(self.preview, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("적용")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._refresh)
        for sig in (self.edit.textChanged, self.size.valueChanged, self.font_combo.currentIndexChanged,
                    self.fill_chk.toggled):
            sig.connect(lambda *_: self._timer.start())
        self.color.on_change = self.fill_color.on_change = self._timer.start
        self._chain_cache = {}
        self._refresh()
        self.edit.setFocus()
        self.edit.selectAll()

    # ---- 결과
    def chain(self):
        data = self.font_combo.currentData()
        if data is None:  # 직접 입력 후 일치 항목 찾기
            idx = self.font_combo.findText(self.font_combo.currentText(), Qt.MatchContains)
            data = self.font_combo.itemData(idx) if idx >= 0 else ("auto", None)
        key = (data[0], id(data[1]))
        if key in self._chain_cache:
            return self._chain_cache[key]
        kind, obj = data
        if kind == "auto":
            ch = self.pdf.chain_for(self.style)
        elif kind == "doc":
            ch = build_chain(obj.font, obj.flags, self.pdf.embedded)
        else:
            ch = build_chain("", 0, None, override=obj)
        self._chain_cache[key] = ch
        return ch

    def values(self):
        return dict(text=self.edit.toPlainText(), chain=self.chain(), size=self.size.value(),
                    color=self.color.rgb, fill=self.fill_color.rgb if self.fill_chk.isChecked() else None)

    # ---- 미리보기
    def _refresh(self):
        text = self.edit.toPlainText() or " "
        ch = self.chain()
        desc = ch.describe(text)
        warn = ""
        kinds = {ch.pick(c).kind for c in text if not c.isspace()}
        if "fallback" in kinds and (self.font_combo.currentData() or ("auto",))[0] == "auto" and \
                self.item and not self.item.invisible:
            warn = ("<br><b>⚠ 일부 글자가 원본 글꼴에 없어 대체 글꼴로 표시됩니다.</b> "
                    "원본 글꼴을 PC에 설치하면 똑같은 글꼴로 수정됩니다.")
        self.info.setText(f"사용 글꼴: {desc}{warn}")
        try:
            size = self.size.value()
            nlines = text.count("\n") + 1
            d = pymupdf.open()
            pg = d.new_page(width=2400, height=size * 1.4 * nlines + size * 2)
            if self.fill_chk.isChecked():
                pg.draw_rect(pg.rect, color=None, fill=self.fill_color.rgb)
            r = write_text(pg, (6, size * 1.1), text, ch, size, self.color.rgb)
            clip = (pymupdf.Rect(0, 0, r.x1 + 6, r.y1 + size * 0.4)) & pg.rect
            zoom = min(2.0, max(0.2, (self.preview.width() - 10) / max(clip.width, 1)),
                       max(0.2, (self.preview.height() - 6) / max(clip.height, 1)))
            pm = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(img))
        except Exception as e:  # 미리보기 실패는 치명적이지 않음
            self.preview.setText(f"(미리보기 실패: {e})")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_timer"):
            self._timer.start()


def pil_to_pixmap(img: Image.Image, max_w=420, max_h=300) -> QPixmap:
    im = img.copy()
    im.thumbnail((max_w, max_h))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    return QPixmap.fromImage(QImage(ImageQt(im)))


class ImageAdjustDialog(QDialog):
    def __init__(self, parent, img: Image.Image):
        super().__init__(parent)
        self.setWindowTitle("이미지 보정")
        self.src = img.copy()
        self.src.thumbnail((420, 300))
        lay = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(420, 300)
        self.view.setStyleSheet("background:#ddd")
        lay.addWidget(self.view)
        form = QFormLayout()
        self.sliders = {}
        for key, label in (("brightness", "밝기"), ("contrast", "대비"), ("saturation", "채도"), ("sharpness", "선명도")):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 200)
            s.setValue(100)
            s.valueChanged.connect(self._update)
            val = QLabel("100%")
            s.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
            row = QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(val)
            w = QWidget()
            w.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            form.addRow(label, w)
            self.sliders[key] = s
        lay.addLayout(form)
        reset = QPushButton("초기화")
        reset.clicked.connect(lambda: [s.setValue(100) for s in self.sliders.values()])
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("적용")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.addButton(reset, QDialogButtonBox.ResetRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update()

    def values(self):
        return {k: s.value() / 100 for k, s in self.sliders.items()}

    def _update(self):
        v = self.values()
        a = self.src.getchannel("A") if self.src.mode in ("RGBA", "LA") else None
        im = self.src.convert("RGB")
        im = ImageEnhance.Brightness(im).enhance(v["brightness"])
        im = ImageEnhance.Contrast(im).enhance(v["contrast"])
        im = ImageEnhance.Color(im).enhance(v["saturation"])
        im = ImageEnhance.Sharpness(im).enhance(v["sharpness"])
        if a is not None:
            im.putalpha(a)
        self.view.setPixmap(pil_to_pixmap(im))


class CropDialog(QDialog):
    def __init__(self, parent, img: Image.Image):
        super().__init__(parent)
        self.setWindowTitle("이미지 자르기")
        self.base = pil_to_pixmap(img)
        lay = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(self.base.width() + 10, self.base.height() + 10)
        lay.addWidget(self.view)
        form = QFormLayout()
        self.spins = {}
        for key, label in (("l", "왼쪽"), ("t", "위"), ("r", "오른쪽"), ("b", "아래")):
            s = QSpinBox()
            s.setRange(0, 95)
            s.setSuffix(" %")
            s.valueChanged.connect(self._update)
            form.addRow(f"{label}에서 자르기", s)
            self.spins[key] = s
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("자르기")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update()

    def box(self):
        l, t = self.spins["l"].value() / 100, self.spins["t"].value() / 100
        r, b = 1 - self.spins["r"].value() / 100, 1 - self.spins["b"].value() / 100
        if r - l < 0.05:
            r = l + 0.05
        if b - t < 0.05:
            b = t + 0.05
        return (l, t, min(r, 1), min(b, 1))

    def _update(self):
        pm = QPixmap(self.base)
        qp = QPainter(pm)
        l, t, r, b = self.box()
        W, H = pm.width(), pm.height()
        shade = QColor(0, 0, 0, 120)
        qp.fillRect(0, 0, W, int(t * H), shade)
        qp.fillRect(0, int(b * H), W, H, shade)
        qp.fillRect(0, int(t * H), int(l * W), int((b - t) * H), shade)
        qp.fillRect(int(r * W), int(t * H), W, int((b - t) * H), shade)
        qp.setPen(QPen(QColor(255, 140, 0), 2))
        qp.drawRect(int(l * W), int(t * H), int((r - l) * W), int((b - t) * H))
        qp.end()
        self.view.setPixmap(pm)


class TextResultDialog(QDialog):
    def __init__(self, parent, title, text, note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            lay.addWidget(n)
        ed = QPlainTextEdit(text)
        lay.addWidget(ed)
        row = QHBoxLayout()
        cp = QPushButton("전체 복사")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(ed.toPlainText()))
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(cp)
        row.addWidget(close)
        lay.addLayout(row)
