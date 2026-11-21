@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title PDF 편집기 - 설치 파일 만들기
echo ============================================================
echo   PDF 편집기  Windows 설치 파일 만들기
echo ============================================================
echo.

rem ---- 1. 파이썬 확인 ----
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [오류] 파이썬이 설치되어 있지 않습니다.
  echo   https://www.python.org/downloads/ 에서 Python 3.12 를 설치하세요.
  echo   설치 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
  goto fail
)
echo [1/4] 파이썬 확인 완료
%PY% --version

rem ---- 2. 가상환경 + 라이브러리 ----
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv || goto fail
)
set "VPY=.venv\Scripts\python.exe"
echo [2/4] 라이브러리 설치 중... (처음 한 번은 몇 분 걸립니다)
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt pyinstaller || goto fail

rem ---- 3. 실행 파일 만들기 ----
echo [3/4] 실행 파일 만드는 중...
"%VPY%" -m PyInstaller --noconfirm --clean PdfEditor.spec || goto fail
echo     완료: dist\PdfEditor\PdfEditor.exe

rem ---- 4. 설치 파일 만들기 (Inno Setup) ----
echo [4/4] 설치 파일 만드는 중...
call :findiscc
if not defined ISCC (
  echo     Inno Setup 이 없어 설치합니다. ^(winget^)
  winget install -e --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements >nul 2>nul
  call :findiscc
)
if not defined ISCC (
  echo.
  echo [안내] Inno Setup 을 찾지 못했습니다.
  echo   https://jrsoftware.org/isdl.php 에서 설치 후 이 파일을 다시 실행하거나,
  echo   dist\PdfEditor 폴더를 그대로 복사해서 PdfEditor.exe 를 실행해도 됩니다.
  goto done
)
"%ISCC%" installer.iss || goto fail
echo.
echo ============================================================
echo   완료!  installer_output 폴더의 PdfEditor_Setup_2.3.0.exe 를
echo   실행하면 설치됩니다.
echo ============================================================
start "" "installer_output"
goto done

:findiscc
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
exit /b 0

:fail
echo.
echo [실패] 위 오류 메시지를 확인해 주세요.
pause
exit /b 1

:done
pause
exit /b 0
