"""리본 메뉴 (그룹 이름이 있는 오피스/알PDF 스타일).

창이 좁아지면 오른쪽 그룹부터 단계적으로 줄어듭니다 (기능은 숨기지 않음):
  0 = 보통(큰 버튼) → 1 = 작게(작은 버튼 세 줄) → 2 = 접힘(그룹 이름 버튼 하나 + 드롭다운 메뉴)
그래도 모자라면 그때만 가로로 스크롤합니다.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

LARGE_ICON = 26
SMALL_ICON = 16
MODE_FULL, MODE_COMPACT, MODE_COLLAPSED = 0, 1, 2


def large_button(action: QAction) -> QToolButton:
    b = QToolButton()
    b.setDefaultAction(action)
    fm = b.fontMetrics()
    w = max(fm.horizontalAdvance(t) for t in (action.text() or " ").split("\n")) + 26
    b.setMinimumWidth(max(56, w))
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setIconSize(QSize(LARGE_ICON, LARGE_ICON))
    b.setProperty("large", True)
    b.setAutoRaise(True)
    b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    return b


def small_button(action: QAction) -> QToolButton:
    b = QToolButton()
    b.setDefaultAction(action)
    b.setMinimumWidth(int(b.fontMetrics().horizontalAdvance(action.text()) * 1.08) + SMALL_ICON + 34)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setIconSize(QSize(SMALL_ICON, SMALL_ICON))
    b.setProperty("small", True)
    b.setAutoRaise(True)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return b


def _column(widgets) -> QVBoxLayout:
    col = QVBoxLayout()
    col.setSpacing(0)
    col.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        col.addWidget(w)
    col.addStretch()
    return col


class RibbonGroup(QWidget):
    """[버튼들]
       그룹 이름

    같은 QAction 으로 세 가지 모양(보통/작게/접힘)을 만들어 두고, set_mode 로 하나만 보여 줌.
    QAction 을 함께 쓰므로 체크·사용 가능 상태는 세 모양에서 항상 같음."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("RibbonGroup")
        self.title = title
        self.items: list = []          # ("large", QAction) / ("smalls", [QAction|QWidget]) / ("widget", QWidget)
        self.mode = MODE_FULL
        self._built_alt = False
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 2)
        v.setSpacing(1)
        self.row = QHBoxLayout()        # 보통 모양 (기존과 같음)
        self.row.setSpacing(2)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.full_w = QWidget()
        self.full_w.setLayout(self.row)
        self.compact_w: QWidget | None = None
        self.coll_btn: QToolButton | None = None
        self.body = QHBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        self.body.addWidget(self.full_w)
        v.addLayout(self.body, 1)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("RibbonGroupTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.title_label)

    # ---- 보통 모양 만들기 (기존 API)
    def add_large(self, action: QAction):
        self.items.append(("large", action))
        self.row.addWidget(large_button(action))

    def add_smalls(self, actions: list):
        self.items.append(("smalls", list(actions)))
        self.row.addLayout(_column([a if isinstance(a, QWidget) else small_button(a) for a in actions]))

    def add_widget(self, w: QWidget):
        self.items.append(("widget", w))
        self.row.addWidget(w)

    # ---- 줄어든 모양
    @property
    def can_shrink(self) -> bool:
        """일반 위젯(콤보 상자 등)은 한 곳에만 둘 수 있으므로, 그런 그룹은 줄이지 않음."""
        return not any(kind == "widget" or (kind == "smalls" and any(isinstance(a, QWidget) for a in acts))
                       for kind, acts in self.items)

    def actions_in_order(self) -> list:
        out = []
        for kind, a in self.items:
            if kind == "large":
                out.append(a)
            elif kind == "smalls":
                out += [x for x in a if isinstance(x, QAction)]
        return out

    def _build_alternates(self):
        if self._built_alt or not self.can_shrink:
            return
        self._built_alt = True
        # 작게: 큰 버튼을 작은 버튼으로 바꿔 세 개씩 세로로 쌓음 (원래 작은 버튼 묶음은 그대로)
        self.compact_w = QWidget()
        h = QHBoxLayout(self.compact_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        pending = []
        for kind, a in self.items:
            if kind == "large":
                pending.append(small_button(a))
                if len(pending) == 3:
                    h.addLayout(_column(pending))
                    pending = []
            else:
                if pending:
                    h.addLayout(_column(pending))
                    pending = []
                h.addLayout(_column([small_button(x) for x in a]))
        if pending:
            h.addLayout(_column(pending))
        self.compact_w.hide()
        self.body.addWidget(self.compact_w)
        # 접힘: 그룹 이름 버튼 하나 + 드롭다운 메뉴
        b = QToolButton()
        b.setObjectName("RibbonCollapsed")
        b.setText(self.title)
        b.setToolTip(f"{self.title}: " + ", ".join(a.text().replace("\n", " ") for a in self.actions_in_order()))
        b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        b.setIconSize(QSize(LARGE_ICON, LARGE_ICON))
        b.setProperty("large", True)
        b.setAutoRaise(True)
        b.setPopupMode(QToolButton.InstantPopup)
        b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        b.setMinimumWidth(max(56, b.fontMetrics().horizontalAdvance(self.title) + 30))
        m = QMenu(b)
        first = True
        for kind, a in self.items:
            if not first:
                m.addSeparator()
            first = False
            for act in ([a] if kind == "large" else a):
                m.addAction(act)
        b.setMenu(m)
        b.hide()
        self.coll_btn = b
        self.body.addWidget(b)

    def set_mode(self, mode: int):
        if not self.can_shrink:
            mode = MODE_FULL
        if mode != MODE_FULL:
            self._build_alternates()
        if mode == MODE_COLLAPSED and self.coll_btn is not None:
            acts = self.actions_in_order()
            if acts:
                self.coll_btn.setIcon(acts[0].icon())   # 아이콘은 나중에 바뀔 수 있어 접을 때마다 다시 가져옴
        self.mode = mode
        self.full_w.setVisible(mode == MODE_FULL)
        if self.compact_w is not None:
            self.compact_w.setVisible(mode == MODE_COMPACT)
        if self.coll_btn is not None:
            self.coll_btn.setVisible(mode == MODE_COLLAPSED)
        self.title_label.setVisible(mode != MODE_COLLAPSED)  # 접힌 버튼에 이미 그룹 이름이 있음

    def width_for(self, mode: int) -> int:
        """그 모양일 때의 폭. 레이아웃 갱신은 비동기라 모양을 바꿔 재지 않고, 각 모양 위젯의 크기 힌트로 바로 계산."""
        if not self.can_shrink:
            mode = MODE_FULL
        if mode != MODE_FULL:
            self._build_alternates()
        rep = {MODE_FULL: self.full_w, MODE_COMPACT: self.compact_w, MODE_COLLAPSED: self.coll_btn}[mode]
        m = self.layout().contentsMargins()
        w = rep.sizeHint().width()
        if mode != MODE_COLLAPSED:
            w = max(w, self.title_label.sizeHint().width())
        return w + m.left() + m.right()


class RibbonPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonPage")
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(6, 2, 6, 2)
        self.h.setSpacing(2)
        self._first = True
        self.groups: list[RibbonGroup] = []
        self._widths: list[list[int]] | None = None   # 그룹별 [보통, 작게, 접힘] 폭 (글꼴·스타일이 바뀌면 다시 잼)
        self._overhead = 0

    def add_group(self, title: str, items: list) -> RibbonGroup:
        """items: QAction (큰 버튼) 또는 list[QAction|QWidget] (작은 버튼 세로 묶음) 또는 QWidget"""
        if not self._first:
            sep = QFrame()
            sep.setObjectName("RibbonSep")
            sep.setFixedWidth(1)
            sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.h.addWidget(sep)
        self._first = False
        g = RibbonGroup(title)
        for it in items:
            if isinstance(it, QAction):
                g.add_large(it)
            elif isinstance(it, list):
                g.add_smalls(it)
            elif isinstance(it, QWidget):
                g.add_widget(it)
        self.h.addWidget(g)
        self.groups.append(g)
        return g

    def finish(self):
        self.h.addStretch(1)

    def changeEvent(self, e):
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._widths = None
        super().changeEvent(e)

    def _measure(self):
        self._widths = [[g.width_for(m) for m in (MODE_FULL, MODE_COMPACT, MODE_COLLAPSED)] for g in self.groups]
        # 그룹 밖의 폭: 여백 + 구분선(1px) + 항목 사이 간격 (구분선·그룹·끝 여백 막대)
        m = self.h.contentsMargins()
        n_items = self.h.count()
        self._overhead = (m.left() + m.right() + (len(self.groups) - 1)
                          + self.h.spacing() * max(0, n_items - 1))

    def plan_modes(self, avail: int) -> list[int]:
        """폭 avail 에 맞는 그룹별 모양. 오른쪽 그룹부터 '작게', 그래도 넓으면 오른쪽부터 '접힘'."""
        if self._widths is None:
            self._measure()
        W = self._widths
        modes = [MODE_FULL] * len(self.groups)
        total = self._overhead + sum(w[MODE_FULL] for w in W)
        for target in (MODE_COMPACT, MODE_COLLAPSED):
            for i in reversed(range(len(self.groups))):
                if total <= avail:
                    return modes
                if not self.groups[i].can_shrink or W[i][target] >= W[i][modes[i]]:
                    continue  # 줄여도 좁아지지 않으면 그대로 둠
                total += W[i][target] - W[i][modes[i]]
                modes[i] = target
        return modes

    def fit(self, avail: int):
        modes = self.plan_modes(avail)
        if modes != [g.mode for g in self.groups]:
            for g, m in zip(self.groups, modes):
                g.set_mode(m)
            self.h.invalidate()
            self.updateGeometry()


class RibbonScroll(QScrollArea):
    """리본 한 페이지. 폭이 바뀌면 그룹 모양을 다시 고르고, 다 접어도 모자랄 때만 가로 스크롤."""

    def __init__(self, page: RibbonPage):
        super().__init__()
        self.page = page
        self.setObjectName("RibbonScroll")
        self.setWidget(page)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(page.sizeHint().height() + 2)

    def refit(self):
        self.page.fit(self.viewport().width())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.refit()

    def showEvent(self, e):
        super().showEvent(e)
        self.refit()


def scrollable(page: RibbonPage) -> RibbonScroll:
    """창이 좁으면 그룹을 줄이고, 그래도 모자라면 리본을 옆으로 스크롤."""
    return RibbonScroll(page)
