Target amd64-unicode
ManifestDPIAware true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!define APPNAME "PDF 편집기"
!define APPID "PdfEditorKR"
!define VERSION "2.4.0"
!define EXE "PdfEditor.exe"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"

Name "${APPNAME}"
OutFile "out\PdfEditor_Setup_${VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APPID}"
InstallDirRegKey HKLM "Software\${APPID}" "InstallDir"
RequestExecutionLevel admin
BrandingText "${APPNAME} ${VERSION}"

VIProductVersion "2.4.0.0"
VIAddVersionKey /LANG=1042 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1042 "FileDescription" "${APPNAME} 설치"
VIAddVersionKey /LANG=1042 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1042 "CompanyName" "${APPID}"
VIAddVersionKey /LANG=1042 "LegalCopyright" "PyMuPDF(AGPL-3.0), Qt/PySide6(LGPL-3.0)"

!include "MUI2.nsh"
!include "x64.nsh"
!define MUI_ICON "icon.ico"
!define MUI_UNICON "icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "${APPNAME} 실행"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Korean"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "64비트 Windows 10 이상에서만 설치할 수 있습니다."
    Abort
  ${EndIf}
  SetRegView 64
  SetShellVarContext all
FunctionEnd

Function un.onInit
  SetRegView 64
  SetShellVarContext all
FunctionEnd

Section "프로그램 (필수)" SecMain
  SectionIn RO
  ; 이전 버전 파일 정리
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  SetOutPath "$INSTDIR"
  File /r "dist\PdfEditor\*"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME} 제거.lnk" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "Software\${APPID}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "${APPID}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" 420000
SectionEnd

Section "바탕 화면 바로 가기" SecDesktop
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
SectionEnd

Section "PDF 우클릭 '연결 프로그램'에 추가" SecOpenWith
  ; 기본 PDF 프로그램은 바꾸지 않고 목록에만 추가
  WriteRegStr HKLM "Software\Classes\${APPID}.pdf" "" "PDF 문서"
  WriteRegStr HKLM "Software\Classes\${APPID}.pdf\DefaultIcon" "" "$INSTDIR\${EXE},0"
  WriteRegStr HKLM "Software\Classes\${APPID}.pdf\shell\open\command" "" '"$INSTDIR\${EXE}" "%1"'
  WriteRegStr HKLM "Software\Classes\.pdf\OpenWithProgids" "${APPID}.pdf" ""
  WriteRegStr HKLM "Software\Classes\Applications\${EXE}\SupportedTypes" ".pdf" ""
  WriteRegStr HKLM "Software\Classes\Applications\${EXE}\shell\open\command" "" '"$INSTDIR\${EXE}" "%1"'
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "PDF 편집기 프로그램과 OCR(한국어·영어) 데이터"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "바탕 화면에 바로 가기를 만듭니다"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecOpenWith} "PDF 파일을 우클릭했을 때 '연결 프로그램' 목록에 표시합니다 (기본 프로그램은 바뀌지 않음)"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "Software\${APPID}"
  DeleteRegKey HKLM "Software\Classes\${APPID}.pdf"
  DeleteRegValue HKLM "Software\Classes\.pdf\OpenWithProgids" "${APPID}.pdf"
  DeleteRegKey HKLM "Software\Classes\Applications\${EXE}"
SectionEnd
