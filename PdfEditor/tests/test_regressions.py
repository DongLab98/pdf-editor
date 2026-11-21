"""회귀 테스트: 이미지 저장 덮어쓰기, 인라인 편집 대상 탭/롤백, 오래된 찾기 결과.

실행:  set QT_QPA_PLATFORM=offscreen
       python -W ignore -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PDFEDITOR_ADS_URL"] = ""  # 광고 내려받기 끔

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pymupdf  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from pdfeditor import engine, fontmgr, mainwindow  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)
fontmgr.SYSTEM_FONTS.build_async()
fontmgr.SYSTEM_FONTS.ready.wait(180)


def _make_pdf(path, pages):
    d = pymupdf.open()
    for txt in pages:
        p = d.new_page(width=300, height=300)
        p.insert_text((40, 60), txt, fontsize=14)
    d.save(path)
    d.close()


def _make_png(path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.clear_with(200)
    pix.save(path)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pdfeditor_test_")
        ini = os.path.join(self.tmp, "settings.ini")
        self._orig_qsettings = mainwindow.QSettings
        mainwindow.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
        self.dialog_calls = []
        self.save_answer = ("", "")
        self.errors = []
        self._patches = []

        def fake_save(*a, **k):
            self.dialog_calls.append(a)
            return self.save_answer

        def fake_box(kind):
            def f(*a, **k):
                self.errors.append((kind, a[2] if len(a) > 2 else ""))
                return QMessageBox.Discard if kind == "question" else QMessageBox.Ok
            return f

        self._patch(QFileDialog, "getSaveFileName", staticmethod(fake_save))
        for kind in ("critical", "warning", "information", "question"):
            self._patch(QMessageBox, kind, staticmethod(fake_box(kind)))
        self.w = mainwindow.MainWindow()

    def _patch(self, obj, name, value):
        self._patches.append((obj, name, obj.__dict__.get(name)))
        setattr(obj, name, value)

    def tearDown(self):
        for i in range(self.w.docs.count()):
            v = self.w.docs.widget(i)
            if isinstance(v, mainwindow.DocView):
                v.pdf.dirty = False
        self.w.close()
        self.w.deleteLater()
        APP.processEvents()
        for obj, name, old in reversed(self._patches):
            setattr(obj, name, old)
        mainwindow.QSettings = self._orig_qsettings
        shutil.rmtree(self.tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- 1. 이미지 → Ctrl+S
class ImageSaveTest(Base):
    def test_image_save_asks_and_never_overwrites(self):
        png = os.path.join(self.tmp, "x.png")
        _make_png(png)
        existing = os.path.join(self.tmp, "x.pdf")
        with open(existing, "wb") as f:
            f.write(b"KEEP-ME")
        self.w.open_path(png)
        self.assertEqual(self.w.docs.count(), 1)
        self.assertFalse(self.w.save())                 # 대화상자 취소
        self.assertEqual(len(self.dialog_calls), 1, "다른 이름으로 저장 대화상자가 떠야 함")
        with open(existing, "rb") as f:
            self.assertEqual(f.read(), b"KEEP-ME", "기존 x.pdf 를 덮어쓰면 안 됨")
        target = os.path.join(self.tmp, "chosen.pdf")
        self.save_answer = (target, "PDF (*.pdf)")
        self.assertTrue(self.w.save())
        self.assertTrue(os.path.exists(target))
        self.assertEqual(len(self.dialog_calls), 2)
        self.assertTrue(self.w.save())                  # 이제는 그 경로로 바로 저장
        self.assertEqual(len(self.dialog_calls), 2)

    def test_reopen_same_image_focuses_tab(self):
        png = os.path.join(self.tmp, "y.png")
        _make_png(png)
        self.w.open_path(png)
        self.w.open_path(png)
        self.assertEqual(self.w.docs.count(), 1)

    def test_reopen_image_after_save_focuses_tab(self):
        png = os.path.join(self.tmp, "z.png")
        _make_png(png)
        self.w.open_path(png)
        self.save_answer = (os.path.join(self.tmp, "saved.pdf"), "PDF (*.pdf)")
        self.assertTrue(self.w.save())
        self.w.open_path(png)                           # 원본 이미지를 다시 열기
        self.w.open_path(os.path.join(self.tmp, "saved.pdf"))  # 저장한 PDF 열기
        self.assertEqual(self.w.docs.count(), 1)

    def test_pdf_save_in_place_without_dialog(self):
        pdf = os.path.join(self.tmp, "doc.pdf")
        _make_pdf(pdf, ["hello"])
        self.w.open_path(pdf)
        v = self.w.view
        v.pdf.rotate_page(0)
        self.assertTrue(self.w.save())
        self.assertEqual(self.dialog_calls, [])
        self.assertEqual(pymupdf.open(pdf)[0].rotation, 90)


# ----------------------------------------------------------------------------- 2. 인라인 편집
class InlineCommitTest(Base):
    def test_tab_switch_commits_into_own_view(self):
        a = os.path.join(self.tmp, "a.pdf")
        b = os.path.join(self.tmp, "b.pdf")
        _make_pdf(a, ["alpha text"])
        _make_pdf(b, ["bravo text"])
        self.w.open_path(a)
        va = self.w.view
        self.w.open_path(b)
        vb = self.w.view
        self.w.docs.setCurrentWidget(va)
        APP.processEvents()
        refreshed = []
        for v, name in ((va, "A"), (vb, "B")):
            orig = v.refresh_pages
            v.refresh_pages = lambda pages=None, o=orig, n=name: (refreshed.append(n), o(pages))
        c = va.canvases[0]
        item = va.pdf.text_items(0, c.line_mode, c.para_mode)[0]
        self.w.start_inline(c, item=item)
        self.assertIsNotNone(self.w.inline)
        self.w.inline.edit.setPlainText("CHANGED")
        self.w.docs.setCurrentWidget(vb)               # 탭 전환 → 자동 적용
        APP.processEvents()
        self.assertIn("CHANGED", va.pdf.page_text(0))
        self.assertNotIn("CHANGED", vb.pdf.page_text(0))
        self.assertIn("A", refreshed, "편집한 탭(A)을 다시 그려야 함")
        self.assertNotIn("B", refreshed, "다른 탭(B)을 다시 그리면 안 됨")
        self.assertTrue(self.w.docs.tabText(self.w.docs.indexOf(va)).endswith("*"))

    def test_failed_write_rolls_back_and_keeps_text(self):
        a = os.path.join(self.tmp, "a.pdf")
        _make_pdf(a, ["original words"])
        self.w.open_path(a)
        v = self.w.view
        c = v.canvases[0]
        item = v.pdf.text_items(0, c.line_mode, c.para_mode)[0]
        n_undo, dirty0 = len(v.pdf.undo_stack), v.pdf.dirty
        orig = fontmgr.write_block

        def boom(*a, **k):
            raise RuntimeError("simulated write failure")
        fontmgr.write_block = boom
        try:
            self.w.start_inline(c, item=item)
            self.w.inline.edit.setPlainText("TYPED TEXT")
            self.w.commit_inline()
        finally:
            fontmgr.write_block = orig
        self.assertIn("original words", v.pdf.page_text(0), "실패 시 원래 글자가 남아 있어야 함")
        self.assertEqual(len(v.pdf.undo_stack), n_undo)
        self.assertEqual(v.pdf.dirty, dirty0)
        self.assertEqual(QApplication.clipboard().text(), "TYPED TEXT")
        self.assertTrue(any(k == "critical" for k, _ in self.errors))


class EngineRollbackTest(unittest.TestCase):
    def test_write_paragraph_failure_restores_document(self):
        D = engine.PdfDocument()
        D.new_blank()
        D.add_text(0, pymupdf.Point(60, 60), "keep this", 20, (0, 0, 0), D.chain_for(None))
        it = D.text_items(0)[0]
        n_undo, rev = len(D.undo_stack), D.revision
        orig = fontmgr.write_block
        fontmgr.write_block = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        try:
            with self.assertRaises(RuntimeError):
                D.write_paragraph(0, it, ["new"], origin=it.origin, box_width=200, chain=D.chain_for(it),
                                  size=20, color=(0, 0, 0), pitch=25)
        finally:
            fontmgr.write_block = orig
        self.assertIn("keep this", D.page_text(0))
        self.assertEqual(len(D.undo_stack), n_undo)
        self.assertNotEqual(D.revision, rev)
        self.assertTrue(D.undo())                       # 이전 실행 취소 기록은 그대로 동작
        self.assertNotIn("keep this", D.page_text(0))

    def test_rollback_with_full_undo_stack_keeps_history(self):
        D = engine.PdfDocument()
        D.new_blank()
        D.add_text(0, pymupdf.Point(60, 60), "keep this", 20, (0, 0, 0), D.chain_for(None))
        for _ in range(engine.MAX_UNDO):               # 실행 취소 기록을 가득 채움
            D.rotate_page(0, 0)
        self.assertEqual(len(D.undo_stack), engine.MAX_UNDO)
        before = list(D.undo_stack)
        it = D.text_items(0)[0]
        orig = fontmgr.write_block
        fontmgr.write_block = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        try:
            with self.assertRaises(RuntimeError):
                D.write_paragraph(0, it, ["new"], origin=it.origin, box_width=200, chain=D.chain_for(it),
                                  size=20, color=(0, 0, 0), pitch=25)
        finally:
            fontmgr.write_block = orig
        self.assertEqual(D.undo_stack, before, "가장 오래된 기록까지 그대로 남아야 함")
        self.assertIn("keep this", D.page_text(0))


# ----------------------------------------------------------------------------- 3. 찾기
class SearchTest(Base):
    def _open3(self):
        p = os.path.join(self.tmp, "s.pdf")
        _make_pdf(p, ["foo one", "nothing", "foo three"])
        self.w.open_path(p)
        return self.w.view

    def test_same_query_cycles_like_before(self):
        v = self._open3()
        self.w.find_edit.setText("foo")
        self.w.find_next()
        self.assertEqual(v.search_idx, 0)
        self.w.find_next()
        self.assertEqual(v.search_idx, 1)
        self.assertEqual(len(v.search_hits), 2)

    def test_find_after_page_delete_does_not_crash(self):
        v = self._open3()
        self.w.find_edit.setText("foo")
        self.w.find_next()

        def op():
            v.pdf.delete_page(2)
        self.w._page_op(op, 0)
        self.w.find_next()                              # 예전에는 IndexError
        self.assertEqual(len(v.search_hits), 1)
        self.assertTrue(all(p < len(v.canvases) for p, _ in v.search_hits))

    def test_edit_clears_stale_highlights(self):
        v = self._open3()
        self.w.find_edit.setText("foo")
        self.w.find_next()
        self.assertTrue(v.canvases[0].highlights)
        self.w._do(0, lambda: v.pdf.rotate_page(0), "회전")
        self.assertEqual(v.canvases[0].highlights, [])
        self.w.find_next()                              # 다시 찾으면 새로 계산
        self.assertEqual(v.search_idx, 0)


# ----------------------------------------------------------------------------- 4. 최근 파일
class RecentListTest(Base):
    def test_activate_none_or_placeholder_does_not_crash(self):
        self.w._open_recent_item(None)                  # 예전에는 AttributeError
        self.w.recent_list.clear()
        self.w._update_recent()                         # 최근 파일이 없으면 안내 줄 하나
        self.w._open_recent_item(self.w.recent_list.item(0))
        self.assertEqual(self.w.docs.count(), 0)
        self.assertEqual(self.errors, [], "경고창이 뜨면 안 됨")

    def test_activate_recent_file_opens_it(self):
        pdf = os.path.join(self.tmp, "recent.pdf")
        _make_pdf(pdf, ["recent"])
        self.w.open_path(pdf)
        self.w.close_tab(0)
        item = next(self.w.recent_list.item(i) for i in range(self.w.recent_list.count())
                    if self.w.recent_list.item(i).data(mainwindow.Qt.UserRole) == pdf)
        self.w._open_recent_item(item)
        self.assertEqual(self.w.docs.count(), 1)


# ----------------------------------------------------------------------------- 5. 리본 배치
class RibbonLayoutTest(Base):
    def test_ribbon_full_width_and_stable_when_document_opens(self):
        self.assertIs(self.w.menuWidget(), self.w.ribbon, "리본은 도크 위 메뉴 위젯 자리에 있어야 함")
        self.w.resize(1200, 800)
        self.w.show()
        APP.processEvents()
        x0 = self.w.ribbon.mapTo(self.w, mainwindow.QPoint(0, 0)).x()
        pdf = os.path.join(self.tmp, "r.pdf")
        _make_pdf(pdf, ["ribbon"])
        self.w.open_path(pdf)
        APP.processEvents()
        self.assertTrue(self.w.side_dock.isVisible())
        self.assertEqual(self.w.ribbon.mapTo(self.w, mainwindow.QPoint(0, 0)).x(), x0,
                         "문서를 열어도 리본이 옆으로 밀리면 안 됨")
        self.assertEqual(x0, 0)
        self.assertEqual(self.w.ribbon.width(), self.w.width())

    def test_all_ribbon_pages_same_height(self):
        hs = {self.w.ribbon_tabs.widget(i).height() for i in range(self.w.ribbon_tabs.count())}
        self.assertEqual(len(hs), 1, f"탭마다 리본 높이가 다름: {hs}")


# ----------------------------------------------------------------------------- 6. 좁은 창의 리본
class RibbonAdaptTest(Base):
    def test_groups_shrink_right_first_and_keep_all_commands(self):
        from pdfeditor import ribbon
        page = self.w.ribbon_scrolls[0].page
        all_actions = {id(a) for g in page.groups for a in g.actions_in_order()}
        page.fit(100000)                                 # 넓으면 모두 보통
        self.assertTrue(all(g.mode == ribbon.MODE_FULL for g in page.groups))
        widths = page._widths
        full = page._overhead + sum(w[0] for w in widths)
        page.fit(full - 60)                              # 조금 좁으면 오른쪽부터 줄어듦
        modes = [g.mode for g in page.groups]
        self.assertNotEqual(modes[-1], ribbon.MODE_FULL, f"맨 오른쪽 그룹부터 줄어야 함: {modes}")
        self.assertEqual(modes[0], ribbon.MODE_FULL, f"왼쪽 그룹은 그대로여야 함: {modes}")
        page.fit(10)                                     # 아주 좁으면 줄일 수 있는 그룹은 모두 접힘
        for g in page.groups:
            if g.can_shrink:
                self.assertEqual(g.mode, ribbon.MODE_COLLAPSED)
        reachable = {id(a) for g in page.groups if g.coll_btn is not None
                     for a in g.coll_btn.menu().actions() if not a.isSeparator()}
        self.assertEqual(reachable, all_actions, "접어도 모든 명령은 메뉴에서 쓸 수 있어야 함")

    def test_group_with_widget_never_shrinks(self):
        page = self.w.ribbon_scrolls[2].page            # 주석 탭: '스타일' 그룹에 굵기 콤보 상자
        style = next(g for g in page.groups if g.title == "스타일")
        self.assertFalse(style.can_shrink)
        page.fit(10)
        self.assertEqual(style.mode, 0)

    def test_minimize_ribbon_toggle_and_persist(self):
        self.w.resize(1200, 800)
        self.w.show()
        APP.processEvents()
        h_full = self.w.ribbon.sizeHint().height()
        self.w.a_ribbon_min.trigger()                    # Ctrl+F1 과 같은 동작
        APP.processEvents()
        self.assertTrue(self.w.a_ribbon_min.isChecked())
        self.assertLess(self.w.ribbon.sizeHint().height(), h_full - 50)
        self.assertTrue(self.w.settings.value("ribbon_min", False, type=bool))
        self.w._ribbon_tab_clicked(1)                    # 접힌 상태에서 탭을 누르면 펼침
        self.w._ribbon_tab_double_clicked(1)             # 같은 두 번 클릭의 두 번째 신호는 다시 접지 않음
        APP.processEvents()
        self.assertFalse(self.w.a_ribbon_min.isChecked())
        self.assertEqual(self.w.ribbon.sizeHint().height(), h_full)
        self.w._ribbon_just_expanded = False
        self.w._ribbon_tab_double_clicked(1)             # 펼친 상태에서 두 번 클릭 → 접기
        self.assertTrue(self.w.a_ribbon_min.isChecked())


if __name__ == "__main__":
    unittest.main()
