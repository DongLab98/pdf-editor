"""문서 도구 대화상자."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QRadioButton, QSlider, QSpinBox, QTabWidget, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)

from . import tools
from .dialogs import ColorButton

PDF_IMG_FILTER = "PDF/이미지 (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"


def _buttons(dlg, ok="확인"):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok)
    bb.button(QDialogButtonBox.Cancel).setText("취소")
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class PageRangeBox(QGroupBox):
    """전체 / 현재 페이지 / 범위 지정."""

    def __init__(self, total, current, title="페이지 범위", allow_current=True):
        super().__init__(title)
        self.total, self.current = total, current
        lay = QHBoxLayout(self)
        self.all = QRadioButton("전체")
        self.cur = QRadioButton(f"현재 페이지({current + 1})")
        self.rng = QRadioButton("범위:")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("예: 1-3, 5, 8-")
        self.all.setChecked(True)
        self.edit.textEdited.connect(lambda _t: self.rng.setChecked(True))
        lay.addWidget(self.all)
        if allow_current:
            lay.addWidget(self.cur)
        else:
            self.cur.hide()
        lay.addWidget(self.rng)
        lay.addWidget(self.edit, 1)

    def pages(self):
        if self.cur.isChecked():
            return [self.current]
        if self.rng.isChecked():
            return tools.parse_range(self.edit.text(), self.total)
        return list(range(self.total))


class FileListWidget(QListWidget):
    def __init__(self, filt=PDF_IMG_FILTER):
        super().__init__()
        self.filt = filt
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def add_paths(self, paths):
        for p in paths:
            it = QListWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            it.setData(Qt.UserRole, p)
            self.addItem(it)

    def paths(self):
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        else:
            super().dropEvent(e)


class FileListDialog(QDialog):
    """PDF 합치기 / 이미지→PDF 공용."""

    def __init__(self, parent, title, filt, initial=(), ok="합치기", extra=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 440)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("파일을 추가하고 순서를 정하세요 (끌어서 순서 변경, 탐색기에서 끌어다 놓기 가능)"))
        row = QHBoxLayout()
        self.list = FileListWidget(filt)
        self.list.add_paths(initial)
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        for text, fn in (("추가…", self._add), ("삭제", self._remove), ("위로", lambda: self._move(-1)),
                         ("아래로", lambda: self._move(1)), ("이름순 정렬", self._sort)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch()
        row.addLayout(col)
        lay.addLayout(row)
        self.extra = extra
        if extra is not None:
            lay.addWidget(extra)
        lay.addWidget(_buttons(self, ok))
        self.filt = filt

    def _add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "파일 추가", "", self.filt)
        self.list.add_paths(paths)

    def _remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def _move(self, d):
        r = self.list.currentRow()
        if r < 0 or not (0 <= r + d < self.list.count()):
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + d, it)
        self.list.setCurrentRow(r + d)

    def _sort(self):
        ps = sorted(self.list.paths(), key=lambda p: os.path.basename(p).lower())
        self.list.clear()
        self.list.add_paths(ps)

    def accept(self):
        if self.list.count() < 1:
            QMessageBox.warning(self, self.windowTitle(), "파일을 추가하세요.")
            return
        super().accept()


class SplitDialog(QDialog):
    def __init__(self, parent, total):
        super().__init__(parent)
        self.setWindowTitle("PDF 분할")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"전체 {total}페이지"))
        self.each = QRadioButton("한 페이지씩 나누기")
        self.every = QRadioButton("일정 페이지씩 나누기:")
        self.n = QSpinBox()
        self.n.setRange(1, max(1, total))
        self.n.setValue(min(2, total))
        self.n.setSuffix(" 페이지씩")
        self.ranges = QRadioButton("범위별로 나누기:")
        self.rtext = QLineEdit()
        self.rtext.setPlaceholderText("예: 1-3; 4-10; 11-   (세미콜론으로 파일 구분)")
        self.each.setChecked(True)
        g = QGridLayout()
        g.addWidget(self.each, 0, 0, 1, 2)
        g.addWidget(self.every, 1, 0)
        g.addWidget(self.n, 1, 1)
        g.addWidget(self.ranges, 2, 0)
        g.addWidget(self.rtext, 2, 1)
        lay.addLayout(g)
        self.n.valueChanged.connect(lambda: self.every.setChecked(True))
        self.rtext.textEdited.connect(lambda: self.ranges.setChecked(True))
        lay.addWidget(_buttons(self, "분할"))

    def values(self):
        if self.each.isChecked():
            return "each", None
        if self.every.isChecked():
            return "every", self.n.value()
        return "ranges", self.rtext.text()


class HeaderFooterDialog(QDialog):
    def __init__(self, parent, total, current, start_tab=0):
        super().__init__(parent)
        self.setWindowTitle("페이지 번호 / 머리글·바닥글")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        # 페이지 번호
        w1 = QWidget()
        f1 = QFormLayout(w1)
        self.pos = QComboBox()
        for label, key in (("아래 가운데", "bottom-center"), ("아래 오른쪽", "bottom-right"), ("아래 왼쪽", "bottom-left"),
                           ("위 가운데", "top-center"), ("위 오른쪽", "top-right"), ("위 왼쪽", "top-left")):
            self.pos.addItem(label, key)
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for f in ("{p}", "- {p} -", "{p} / {n}", "{p} 페이지", "Page {p} of {n}"):
            self.fmt.addItem(f)
        self.start = QSpinBox()
        self.start.setRange(0, 99999)
        self.start.setValue(1)
        f1.addRow("위치:", self.pos)
        f1.addRow("형식:", self.fmt)
        f1.addRow("시작 번호:", self.start)
        f1.addRow(QLabel("{p} = 페이지 번호, {n} = 전체 페이지 수"))
        self.tabs.addTab(w1, "페이지 번호")
        # 머리글/바닥글
        w2 = QWidget()
        g = QGridLayout(w2)
        self.hf = {}
        for c, name in enumerate(("왼쪽", "가운데", "오른쪽")):
            g.addWidget(QLabel(name), 0, c + 1, alignment=Qt.AlignCenter)
        for r, (key, name) in enumerate((("header", "머리글"), ("footer", "바닥글")), 1):
            g.addWidget(QLabel(name), r, 0)
            self.hf[key] = []
            for c in range(3):
                e = QLineEdit()
                g.addWidget(e, r, c + 1)
                self.hf[key].append(e)
        g.addWidget(QLabel("사용 가능: {p} 페이지 번호, {n} 전체 쪽수, {date} 오늘 날짜, {file} 파일 이름"), 3, 0, 1, 4)
        self.tabs.addTab(w2, "머리글·바닥글")
        self.tabs.setCurrentIndex(start_tab)
        lay.addWidget(self.tabs)
        common = QFormLayout()
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 72)
        self.size.setValue(10)
        self.size.setSuffix(" pt")
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 200)
        self.margin.setValue(28)
        self.margin.setSuffix(" pt")
        self.color = ColorButton((0, 0, 0))
        common.addRow("글자 크기:", self.size)
        common.addRow("여백:", self.margin)
        common.addRow("색:", self.color)
        lay.addLayout(common)
        self.range = PageRangeBox(total, current)
        lay.addWidget(self.range)
        lay.addWidget(_buttons(self, "넣기"))

    def values(self):
        spec = {"size": self.size.value(), "margin": self.margin.value(), "color": self.color.rgb, "start": 1}
        if self.tabs.currentIndex() == 0:
            v, h = self.pos.currentData().split("-")
            texts = ["", "", ""]
            texts[{"left": 0, "center": 1, "right": 2}[h]] = self.fmt.currentText()
            spec["header"] = texts if v == "top" else ["", "", ""]
            spec["footer"] = texts if v == "bottom" else ["", "", ""]
            spec["start"] = self.start.value()
        else:
            spec["header"] = [e.text() for e in self.hf["header"]]
            spec["footer"] = [e.text() for e in self.hf["footer"]]
        return spec, self.range.pages()


class WatermarkDialog(QDialog):
    def __init__(self, parent, total, current):
        super().__init__(parent)
        self.setWindowTitle("워터마크")
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        w1 = QWidget()
        f = QFormLayout(w1)
        self.text = QLineEdit("대외비")
        self.size = QSpinBox()
        self.size.setRange(8, 300)
        self.size.setValue(60)
        self.color = ColorButton((0.75, 0.1, 0.1))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        self.angle = QSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        self.tiled = QCheckBox("페이지 전체에 반복")
        f.addRow("문자:", self.text)
        f.addRow("크기:", self.size)
        f.addRow("색:", self.color)
        f.addRow("투명도(진하기):", self.opacity)
        f.addRow("각도:", self.angle)
        f.addRow("", self.tiled)
        self.tabs.addTab(w1, "문자")
        w2 = QWidget()
        f2 = QFormLayout(w2)
        row = QHBoxLayout()
        self.img = QLineEdit()
        b = QPushButton("찾기…")
        b.clicked.connect(self._pick)
        row.addWidget(self.img, 1)
        row.addWidget(b)
        rw = QWidget()
        rw.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.scale = QSpinBox()
        self.scale.setRange(5, 100)
        self.scale.setValue(40)
        self.scale.setSuffix(" % (페이지 폭 기준)")
        self.iopacity = QSlider(Qt.Horizontal)
        self.iopacity.setRange(5, 100)
        self.iopacity.setValue(30)
        self.ipos = QComboBox()
        self.ipos.addItem("가운데", "center")
        self.ipos.addItem("오른쪽 위", "top-right")
        self.ipos.addItem("오른쪽 아래", "bottom-right")
        f2.addRow("이미지:", rw)
        f2.addRow("크기:", self.scale)
        f2.addRow("진하기:", self.iopacity)
        f2.addRow("위치:", self.ipos)
        self.tabs.addTab(w2, "이미지")
        lay.addWidget(self.tabs)
        self.range = PageRangeBox(total, current)
        lay.addWidget(self.range)
        lay.addWidget(_buttons(self, "넣기"))

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "워터마크 이미지", "", "이미지 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if p:
            self.img.setText(p)

    def values(self):
        if self.tabs.currentIndex() == 0:
            return "text", dict(text=self.text.text(), size=self.size.value(), color=self.color.rgb,
                                opacity=self.opacity.value() / 100, angle=self.angle.value(),
                                tiled=self.tiled.isChecked()), self.range.pages()
        return "image", dict(image_path=self.img.text(), scale=self.scale.value() / 100,
                             opacity=self.iopacity.value() / 100, position=self.ipos.currentData()), self.range.pages()


class EncryptDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("암호 설정")
        f = QFormLayout(self)
        self.user = QLineEdit()
        self.user.setEchoMode(QLineEdit.Password)
        self.user2 = QLineEdit()
        self.user2.setEchoMode(QLineEdit.Password)
        self.owner = QLineEdit()
        self.owner.setEchoMode(QLineEdit.Password)
        self.owner.setPlaceholderText("비워 두면 열기 암호와 같음")
        f.addRow("문서 열기 암호:", self.user)
        f.addRow("열기 암호 확인:", self.user2)
        f.addRow(QLabel("<b>권한 제한</b> (권한 암호를 아는 사람만 해제 가능)"))
        self.p_print = QCheckBox("인쇄 허용")
        self.p_copy = QCheckBox("내용 복사 허용")
        self.p_mod = QCheckBox("편집·주석 허용")
        for c in (self.p_print, self.p_copy, self.p_mod):
            c.setChecked(True)
            f.addRow("", c)
        f.addRow("권한 암호:", self.owner)
        f.addRow(QLabel("암호화 방식: AES-256"))
        f.addRow(_buttons(self, "저장"))

    def accept(self):
        if self.user.text() != self.user2.text():
            QMessageBox.warning(self, "암호 설정", "열기 암호가 서로 다릅니다.")
            return
        if not self.user.text() and not self.owner.text():
            QMessageBox.warning(self, "암호 설정", "열기 암호 또는 권한 암호를 입력하세요.")
            return
        super().accept()

    def values(self):
        return {"user": self.user.text(), "owner": self.owner.text(), "print": self.p_print.isChecked(),
                "copy": self.p_copy.isChecked(), "modify": self.p_mod.isChecked()}


class NewPdfDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("새 PDF 만들기")
        f = QFormLayout(self)
        self.paper = QComboBox()
        self.paper.addItems(list(tools.PAPER))
        self.orient = QComboBox()
        self.orient.addItems(["세로", "가로"])
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.color = ColorButton((1, 1, 1))
        f.addRow("용지 크기:", self.paper)
        f.addRow("방향:", self.orient)
        f.addRow("페이지 수:", self.count)
        f.addRow("배경색:", self.color)
        f.addRow(_buttons(self, "만들기"))

    def values(self):
        return dict(paper=self.paper.currentText(), landscape=self.orient.currentIndex() == 1,
                    count=self.count.value(), color=self.color.rgb)


class CompressDialog(QDialog):
    def __init__(self, parent, size_bytes):
        super().__init__(parent)
        self.setWindowTitle("PDF 용량 줄이기")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"현재 크기: 약 {size_bytes / 1024 / 1024:.2f} MB"))
        self.group = QButtonGroup(self)
        for i, (key, text) in enumerate((("low", "약하게 — 화질 우선 (이미지 200dpi)"),
                                         ("medium", "보통 — 권장 (이미지 150dpi)"),
                                         ("high", "강하게 — 용량 우선 (이미지 100dpi)"))):
            rb = QRadioButton(text)
            rb.setProperty("key", key)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
            if key == "medium":
                rb.setChecked(True)
        lay.addWidget(QLabel("원본은 그대로 두고 새 파일로 저장합니다."))
        lay.addWidget(_buttons(self, "줄이기"))

    def level(self):
        return self.group.checkedButton().property("key")


class MetadataDialog(QDialog):
    def __init__(self, parent, meta, info_text=""):
        super().__init__(parent)
        self.setWindowTitle("문서 속성")
        f = QFormLayout(self)
        self.edits = {}
        for key, label in (("title", "제목"), ("author", "작성자"), ("subject", "주제"), ("keywords", "키워드")):
            e = QLineEdit(meta.get(key, ""))
            f.addRow(label + ":", e)
            self.edits[key] = e
        for key, label in (("creator", "작성 프로그램"), ("producer", "PDF 변환기")):
            lab = QLabel(meta.get(key, "") or "-")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(label + ":", lab)
        if info_text:
            f.addRow(QLabel(info_text))
        f.addRow(_buttons(self, "적용"))

    def values(self):
        return {k: e.text() for k, e in self.edits.items()}


class ConvertDialog(QDialog):
    def __init__(self, parent, title, total, current, image_opts=False, note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            lay.addWidget(n)
        self.range = PageRangeBox(total, current)
        lay.addWidget(self.range)
        self.fmt = self.dpi = None
        if image_opts:
            f = QFormLayout()
            self.fmt = QComboBox()
            self.fmt.addItems(["png", "jpg"])
            self.dpi = QSpinBox()
            self.dpi.setRange(36, 600)
            self.dpi.setValue(150)
            self.dpi.setSuffix(" dpi")
            f.addRow("형식:", self.fmt)
            f.addRow("해상도:", self.dpi)
            lay.addLayout(f)
        lay.addWidget(_buttons(self, "변환"))


class SignaturePad(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 180)
        self.paths: list[list[QPointF]] = []
        self.pen = QColor(10, 20, 80)
        self.width_ = 3.0
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, _e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.fillRect(self.rect(), QColor("white"))
        qp.setPen(QPen(QColor("#ccc"), 1, Qt.DashLine))
        qp.drawLine(20, self.height() - 40, self.width() - 20, self.height() - 40)
        self._draw(qp, 1.0)
        qp.end()

    def _draw(self, qp, s, offset=QPointF(0, 0)):
        qp.setPen(QPen(self.pen, self.width_ * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for pts in self.paths:
            if len(pts) < 2:
                continue
            path = QPainterPath((pts[0] - offset) * s)
            for p in pts[1:]:
                path.lineTo((p - offset) * s)
            qp.drawPath(path)

    def mousePressEvent(self, e):
        self.paths.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.paths and e.buttons() & Qt.LeftButton:
            self.paths[-1].append(e.position())
            self.update()

    def clear(self):
        self.paths = []
        self.update()

    def to_png(self, path, scale=3):
        pts = [p for ps in self.paths for p in ps]
        if not pts:
            return False
        x0 = min(p.x() for p in pts) - 6
        y0 = min(p.y() for p in pts) - 6
        x1 = max(p.x() for p in pts) + 6
        y1 = max(p.y() for p in pts) + 6
        img = QImage(int((x1 - x0) * scale), int((y1 - y0) * scale), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        qp = QPainter(img)
        qp.setRenderHint(QPainter.Antialiasing)
        self._draw(qp, scale, QPointF(x0, y0))
        qp.end()
        return img.save(path, "PNG")


class SignatureDialog(QDialog):
    """서명 그리기 / 저장된 서명 선택 / 이미지 불러오기 → 선택된 PNG 경로."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("전자 서명")
        self.result_path = None
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        w1 = QWidget()
        v1 = QVBoxLayout(w1)
        v1.addWidget(QLabel("마우스(또는 펜)로 서명을 그리세요."))
        self.pad = SignaturePad()
        v1.addWidget(self.pad)
        row = QHBoxLayout()
        clr = QPushButton("지우기")
        clr.clicked.connect(self.pad.clear)
        self.pcolor = ColorButton((10 / 255, 20 / 255, 80 / 255))
        self.pcolor.on_change = lambda: (setattr(self.pad, "pen", QColor.fromRgbF(*self.pcolor.rgb)), self.pad.update())
        row.addWidget(QLabel("색:"))
        row.addWidget(self.pcolor)
        row.addStretch()
        row.addWidget(clr)
        v1.addLayout(row)
        self.tabs.addTab(w1, "그리기")
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        self.saved = QListWidget()
        self.saved.setViewMode(QListWidget.IconMode)
        self.saved.setIconSize(QSize(180, 70))
        self.saved.setResizeMode(QListWidget.Adjust)
        for p in tools.list_signatures():
            it = QListWidgetItem(QIcon(p), "")
            it.setData(Qt.UserRole, p)
            self.saved.addItem(it)
        self.saved.itemDoubleClicked.connect(lambda _i: self.accept())
        v2.addWidget(self.saved)
        row2 = QHBoxLayout()
        load = QPushButton("이미지 파일 불러오기…")
        load.clicked.connect(self._load)
        dele = QPushButton("선택 삭제")
        dele.clicked.connect(self._delete)
        row2.addWidget(load)
        row2.addStretch()
        row2.addWidget(dele)
        v2.addLayout(row2)
        self.tabs.addTab(w2, f"저장된 서명 ({self.saved.count()})")
        if self.saved.count():
            self.tabs.setCurrentIndex(1)
            self.saved.setCurrentRow(0)
        lay.addWidget(self.tabs)
        lay.addWidget(QLabel("확인 후 문서에서 서명을 넣을 위치를 클릭하세요. 넣은 뒤 드래그로 옮기고 크기를 바꿀 수 있습니다."))
        lay.addWidget(_buttons(self, "서명 넣기"))

    def _load(self):
        p, _ = QFileDialog.getOpenFileName(self, "서명 이미지", "", "이미지 (*.png *.jpg *.jpeg *.bmp *.gif)")
        if p:
            from PIL import Image
            img = Image.open(p).convert("RGBA")
            # 흰 배경 제거
            px = img.load()
            for y in range(img.height):
                for x in range(img.width):
                    r, g, b, a = px[x, y]
                    if r > 235 and g > 235 and b > 235:
                        px[x, y] = (r, g, b, 0)
            out = os.path.join(tools.signatures_dir(), f"sig_{int(time.time())}.png")
            img.save(out)
            it = QListWidgetItem(QIcon(out), "")
            it.setData(Qt.UserRole, out)
            self.saved.insertItem(0, it)
            self.saved.setCurrentRow(0)

    def _delete(self):
        it = self.saved.currentItem()
        if it:
            try:
                os.remove(it.data(Qt.UserRole))
            except OSError:
                pass
            self.saved.takeItem(self.saved.row(it))

    def accept(self):
        if self.tabs.currentIndex() == 0:
            if not self.pad.paths:
                QMessageBox.warning(self, "전자 서명", "서명을 그려 주세요.")
                return
            out = os.path.join(tools.signatures_dir(), f"sig_{int(time.time())}.png")
            self.pad.to_png(out)
            self.result_path = out
        else:
            it = self.saved.currentItem()
            if not it:
                QMessageBox.warning(self, "전자 서명", "서명을 선택하세요.")
                return
            self.result_path = it.data(Qt.UserRole)
        super().accept()


class StampDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("도장(스탬프)")
        self.result_png = None
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        self.date = QCheckBox("날짜 표시")
        self.date.setChecked(True)
        self.color = ColorButton((220 / 255, 30 / 255, 30 / 255))
        self.buttons = []
        for i, s in enumerate(tools.STAMPS):
            b = QToolButton()
            b.setText(s)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setMinimumSize(110, 56)
            b.setStyleSheet("QToolButton{font-size:16px;font-weight:bold;color:#c00;border:2px solid #c00;"
                            "border-radius:8px;background:white} QToolButton:checked{background:#ffe0e0}")
            grid.addWidget(b, i // 5, i % 5)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        lay.addLayout(grid)
        f = QFormLayout()
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("직접 입력 (입력하면 위 선택 대신 사용)")
        f.addRow("문구:", self.custom)
        f.addRow("색:", self.color)
        f.addRow("", self.date)
        lay.addLayout(f)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(90)
        lay.addWidget(self.preview)
        for b in self.buttons:
            b.toggled.connect(self._refresh)
        self.custom.textChanged.connect(self._refresh)
        self.date.toggled.connect(self._refresh)
        self.color.on_change = self._refresh
        lay.addWidget(_buttons(self, "도장 넣기"))
        self._refresh()

    def _text(self):
        if self.custom.text().strip():
            return self.custom.text().strip()
        for b in self.buttons:
            if b.isChecked():
                return b.text()
        return "확인"

    def _refresh(self, *_):
        c = tuple(int(v * 255) for v in self.color.rgb)
        self.result_png = tools.stamp_image(self._text(), c, self.date.isChecked())
        pm = QPixmap()
        pm.loadFromData(self.result_png)
        self.preview.setPixmap(pm.scaledToHeight(min(90, pm.height()), Qt.SmoothTransformation))


class LinkDialog(QDialog):
    def __init__(self, parent, total):
        super().__init__(parent)
        self.setWindowTitle("링크 추가")
        f = QFormLayout(self)
        self.web = QRadioButton("웹 주소:")
        self.url = QLineEdit("https://")
        self.page = QRadioButton("문서의 페이지로 이동:")
        self.pno = QSpinBox()
        self.pno.setRange(1, total)
        self.web.setChecked(True)
        self.url.textEdited.connect(lambda: self.web.setChecked(True))
        self.pno.valueChanged.connect(lambda: self.page.setChecked(True))
        f.addRow(self.web, self.url)
        f.addRow(self.page, self.pno)
        f.addRow(_buttons(self, "추가"))

    def values(self):
        if self.web.isChecked():
            return self.url.text().strip(), None
        return None, self.pno.value() - 1


class HtmlDialog(QDialog):
    def __init__(self, parent, title, html, size=(900, 640)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        lay = QVBoxLayout(self)
        tb = QTextBrowser()
        tb.setHtml(html)
        lay.addWidget(tb)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("닫기")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
