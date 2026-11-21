"""설치/빌드 확인용 자가 진단:  PdfEditor.exe --selftest
결과는 %TEMP%\\pdfeditor_selftest.txt 에 기록, 성공 시 종료 코드 0."""
from __future__ import annotations

import os
import tempfile
import traceback


def run() -> int:
    out = os.path.join(tempfile.gettempdir(), "pdfeditor_selftest.txt")
    log = []
    ok = True
    try:
        import pymupdf

        from . import engine, fontmgr
        fontmgr.SYSTEM_FONTS.build_async()
        fontmgr.SYSTEM_FONTS.ready.wait(180)
        log.append(f"PyMuPDF {pymupdf.VersionBind}, PC 글꼴 {len(fontmgr.SYSTEM_FONTS.fonts)}개")
        log.append(f"tessdata: {engine.tessdata_dir()}  언어: {engine.ocr_languages()}")

        D = engine.PdfDocument()
        D.new_blank()
        res = D.add_text(0, pymupdf.Point(60, 60), "자가 진단 Self Test 123", 26, (0, 0, 0), D.chain_for(None))
        log.append(f"텍스트 추가: {res.chain_desc}")
        it = D.text_items(0)[0]
        res = D.replace_text(0, it, "수정 완료 Edited 456")
        log.append(f"텍스트 수정: {res.chain_desc}")
        assert "수정 완료" in D.page_text(0), "텍스트 수정 실패"

        pix = D.page(0).get_pixmap(dpi=200)
        S = engine.PdfDocument()
        S.new_blank()
        S.page(0).insert_image(S.page(0).rect, pixmap=pix)
        langs = engine.ocr_languages()
        lang = "kor+eng" if {"kor", "eng"} <= set(langs) else (langs[0] if langs else "eng")
        txt = S.ocr_page(0, lang)
        log.append(f"OCR({lang}): {txt!r}")
        assert "456" in txt or "Edited" in txt, "OCR 결과 이상"

        # 주석 / 도구 / 변환
        from . import convert, tools
        rects, sel = D.select_words(0, pymupdf.Point(60, 70), pymupdf.Point(400, 70))
        D.add_markup(0, "highlight", rects, (1, 1, 0))
        D.add_note(0, pymupdf.Point(400, 200), "메모 테스트")
        D.add_shape(0, "arrow", pymupdf.Point(100, 300), pymupdf.Point(300, 250), (1, 0, 0))
        tools.watermark_text(D, [0], "대외비", 50)
        tools.page_numbers(D, [0], "bottom-center", "- {p} -")
        log.append(f"주석 {len(D.annot_items(0))}개, 선택 텍스트: {sel!r}")
        tmp = tempfile.gettempdir()
        convert.to_word(D.doc.tobytes(), os.path.join(tmp, "pdfeditor_selftest.docx"))
        convert.to_excel(D.doc, os.path.join(tmp, "pdfeditor_selftest.xlsx"))
        convert.to_ppt(D.doc, os.path.join(tmp, "pdfeditor_selftest.pptx"))
        import docx
        wtxt = "".join(docx.Document(os.path.join(tmp, "pdfeditor_selftest.docx")).element.body.itertext())
        log.append(f"PDF→워드: {wtxt.strip()[:40]!r}")
        assert "수정" in wtxt, "워드 변환 결과 이상"
        D.save(os.path.join(tmp, "pdfeditor_selftest_enc.pdf"), encrypt={"user": "1234"})
        assert pymupdf.open(os.path.join(tmp, "pdfeditor_selftest_enc.pdf")).needs_pass, "암호 설정 실패"
        log.append("엑셀/PPT 변환, 암호 설정 OK")

        path = os.path.join(tempfile.gettempdir(), "pdfeditor_selftest.pdf")
        D.save(path)
        log.append(f"저장: {path} ({os.path.getsize(path)} bytes)")
        assert os.path.getsize(path) < 3_000_000, "저장 파일이 너무 큼 (글꼴 서브셋 실패)"
        log.append("SELFTEST OK")
    except Exception:
        ok = False
        log.append("SELFTEST FAILED")
        log.append(traceback.format_exc())
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    try:
        import sys
        if sys.stdout is not None:
            sys.stdout.reconfigure(errors="replace")
            print("\n".join(log))
    except Exception:
        pass
    return 0 if ok else 1
