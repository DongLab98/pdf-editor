"""Windows 에서 새 버전 배포 파일 만들기 (런타임·실행 파일은 이전 릴리스 것을 그대로 재사용).

build_on_linux.sh 는 Linux 도구(mingw, makensis, conda 런타임 받기)가 필요합니다. 라이브러리·런처가 바뀌지 않은
버전은 이 스크립트로 이전 포터블 zip 의 runtime/ 과 PdfEditor.exe 를 바이트 그대로 가져오고 app/ 만 새로 넣습니다.

필요: 이전 버전 PdfEditor_Portable_X.zip, NSIS(makensis), git
사용:
  python repackage_windows.py --prev-portable PdfEditor_Portable_2.3.0.zip --version 2.4.0 --out <출력 폴더>
만드는 파일: PdfEditor_Setup_<버전>.exe, PdfEditor_Portable_<버전>.zip, PdfEditor_Source_<버전>.zip
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                 # PdfEditor/ (소스)
REPO = os.path.dirname(SRC)                 # 저장소 루트
APP_ITEMS = ("main.py", "pdfeditor", "tessdata", "assets", "README.md")   # build_on_linux.sh 4) 와 같음
MAKENSIS = [r"C:\Program Files (x86)\NSIS\makensis.exe", r"C:\Program Files\NSIS\makensis.exe", "makensis"]


def run(cmd, **kw):
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def check_versions(version: str):
    """소스 안의 버전 표시가 모두 같은지 확인."""
    checks = {
        os.path.join(SRC, "pdfeditor", "__init__.py"): rf'__version__ = "{re.escape(version)}"',
        os.path.join(HERE, "installer.nsi"): rf'!define VERSION "{re.escape(version)}"',
    }
    for path, pat in checks.items():
        if not re.search(pat, open(path, encoding="utf-8").read()):
            sys.exit(f"버전 불일치: {path} 에 {version} 이 없습니다")


def build(prev_portable: str, version: str, out: str):
    check_versions(version)
    work = os.path.join(out, "_work")
    dist = os.path.join(work, "dist", "PdfEditor")
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(dist)
    # 1) 이전 릴리스의 runtime/ + PdfEditor.exe (바이트 그대로)
    with zipfile.ZipFile(prev_portable) as z:
        prev_cfg = z.read("PdfEditor/app/assets/ads/config.json")
        for info in z.infolist():
            name = info.filename
            if name.startswith("PdfEditor/runtime/") or name == "PdfEditor/PdfEditor.exe":
                z.extract(info, os.path.join(work, "dist"))
    # 2) 새 app/
    app = os.path.join(dist, "app")
    os.makedirs(app)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for item in APP_ITEMS:
        s = os.path.join(SRC, item)
        (shutil.copytree(s, os.path.join(app, item), ignore=ignore) if os.path.isdir(s)
         else shutil.copy2(s, os.path.join(app, item)))
    # 광고 설정은 이전 버전과 같아야 함
    new_cfg = open(os.path.join(app, "assets", "ads", "config.json"), "rb").read()
    if new_cfg != prev_cfg:
        sys.exit("광고 설정(config.json)이 이전 릴리스와 다릅니다")
    # 3) 이전 릴리스처럼 .pyc 를 미리 만들어 둠 (옆자리 .pyc + __pycache__)
    py = os.path.join(dist, "runtime", "python.exe")
    run([py, "-m", "compileall", "-q", "-b", app])
    run([py, "-m", "compileall", "-q", app])
    # 4) 포터블 zip
    portable = os.path.join(out, f"PdfEditor_Portable_{version}.zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        base = os.path.join(work, "dist")
        for root, dirs, files in os.walk(dist):
            dirs.sort()
            rel_root = os.path.relpath(root, base).replace("\\", "/")
            z.write(root, rel_root + "/")
            for f in sorted(files):
                full = os.path.join(root, f)
                z.write(full, f"{rel_root}/{f}")
    # 5) 설치 파일 (installer.nsi 그대로)
    makensis = next((m for m in MAKENSIS if shutil.which(m) or os.path.exists(m)), None)
    if not makensis:
        sys.exit("NSIS(makensis)를 찾을 수 없습니다")
    nsi = open(os.path.join(HERE, "installer.nsi"), encoding="utf-8").read()
    stubs = os.path.join(os.path.dirname(shutil.which(makensis) or makensis), "Stubs")
    if os.path.isdir(stubs) and not any("amd64" in s for s in os.listdir(stubs)):
        # Windows 용 공식 NSIS 에는 64비트 스텁이 없음 → 설치 프로그램만 32비트로 (설치되는 앱은 그대로 64비트,
        # .onInit 의 SetRegView 64 와 $PROGRAMFILES64 로 64비트 레지스트리·Program Files 에 설치됨)
        print("알림: NSIS 에 amd64 스텁이 없어 설치 프로그램을 x86-unicode 로 만듭니다")
        nsi = nsi.replace("Target amd64-unicode", "Target x86-unicode", 1)
    open(os.path.join(work, "installer.nsi"), "w", encoding="utf-8").write(nsi)
    shutil.copy2(os.path.join(SRC, "assets", "icon.ico"), work)
    os.makedirs(os.path.join(work, "out"), exist_ok=True)
    # Windows 의 makensis 는 BOM 없는 스크립트를 시스템 코드 페이지(CP949)로 읽으므로 UTF-8 로 지정
    run([makensis, "/V2", "/INPUTCHARSET", "UTF8", "installer.nsi"], cwd=work)
    shutil.move(os.path.join(work, "out", f"PdfEditor_Setup_{version}.exe"), os.path.join(out, f"PdfEditor_Setup_{version}.exe"))
    # 6) 소스 zip (저장소의 PdfEditor/ 폴더, 커밋된 내용만)
    source = os.path.join(out, f"PdfEditor_Source_{version}.zip")
    run(["git", "-C", REPO, "archive", "--format=zip", "-9", "-o", source, "HEAD", "PdfEditor"])
    print("완료:", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-portable", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    build(a.prev_portable, a.version, a.out)
