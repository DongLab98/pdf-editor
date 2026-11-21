"""리본 메뉴 (그룹 이름이 있는 오피스/알PDF 스타일)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget

LARGE_ICON = 26
SMALL_ICON = 16


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


class RibbonGroup(QWidget):
    """[버튼들]
       그룹 이름"""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("RibbonGroup")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 2)
        v.setSpacing(1)
        self.row = QHBoxLayout()
        self.row.setSpacing(2)
        self.row.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self.row, 1)
        lab = QLabel(title)
        lab.setObjectName("RibbonGroupTitle")
        lab.setAlignment(Qt.AlignCenter)
        v.addWidget(lab)

    def add_large(self, action: QAction):
        self.row.addWidget(large_button(action))

    def add_smalls(self, actions: list):
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setContentsMargins(0, 0, 0, 0)
        for a in actions:
            if isinstance(a, QWidget):
                col.addWidget(a)
            else:
                col.addWidget(small_button(a))
        col.addStretch()
        self.row.addLayout(col)

    def add_widget(self, w: QWidget):
        self.row.addWidget(w)


class RibbonPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonPage")
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(6, 2, 6, 2)
        self.h.setSpacing(2)
        self._first = True

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
        return g

    def finish(self):
        self.h.addStretch(1)


def scrollable(page: RibbonPage) -> QScrollArea:
    """창이 좁으면 리본을 옆으로 스크롤 (버튼이 겹치거나 창이 넓어지지 않게)."""
    sa = QScrollArea()
    sa.setObjectName("RibbonScroll")
    sa.setWidget(page)
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    sa.setFixedHeight(page.sizeHint().height() + 2)
    return sa
