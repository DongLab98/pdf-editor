#!/usr/bin/env bash
# Linux에서 Windows용 PdfEditor.exe + 설치 파일 만들기 (실제 배포본을 만든 방법)
# 필요: python3, pip, zstandard, gcc-mingw-w64-x86-64, nsis, (테스트용) wine64
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"; W="$ROOT/_winbuild"
mkdir -p "$W/pkgs" && cd "$W"
# 1) conda-forge 에서 Windows용 Python 3.12 런타임
curl -s -o /tmp/win64_current.json https://conda.anaconda.org/conda-forge/win-64/current_repodata.json
cp "$HERE/fetch.py" . && python3 fetch.py   # py/ 에 압축 해제 (libpython 은 python 과 같은 버전으로 맞출 것)
# 2) Windows용 라이브러리 (PySide6-Essentials, PyMuPDF, fonttools, Pillow + requirements.txt 의 변환 기능용 패키지)
pip install --target py/Lib/site-packages --platform win_amd64 --python-version 3.12 \
    --implementation cp --only-binary=:all: --no-compile PySide6-Essentials PyMuPDF fonttools Pillow \
    pdf2docx python-docx openpyxl python-pptx "numpy<2" "opencv-python-headless<4.11"
# (불필요한 Qt 모듈/PyMuPDF 부가 패키지 삭제는 README 참고)
# 3) 실행 파일(런처)
cp "$ROOT/assets/icon.ico" . && cp "$HERE/res.rc" "$HERE/launcher.c" .
x86_64-w64-mingw32-windres res.rc -O coff -o res.o
x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -finput-charset=UTF-8 -o PdfEditor.exe launcher.c res.o -static
# 4) 폴더 구성: PdfEditor.exe + runtime/ + app/
rm -rf dist && mkdir -p dist/PdfEditor/app && cp PdfEditor.exe dist/PdfEditor/ && cp -r py dist/PdfEditor/runtime
cp -r "$ROOT/main.py" "$ROOT/pdfeditor" "$ROOT/tessdata" "$ROOT/assets" "$ROOT/README.md" dist/PdfEditor/app/
# 5) 설치 파일
mkdir -p out && cp "$HERE/installer.nsi" . && makensis installer.nsi
echo "완료: $W/out/PdfEditor_Setup_2.4.0.exe"
