; Inno Setup 6 설치 파일 스크립트
; 사용:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; 먼저 PyInstaller 로 dist\PdfEditor 폴더를 만들어 두어야 합니다.

#define AppName "PDF 편집기"
#define AppVersion "2.4.0"
#define AppExe "PdfEditor.exe"

[Setup]
AppId={{6C1D7F0B-4F3A-4C55-9E0B-6A0B2E8D9A41}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=PdfEditorKR
DefaultDirName={autopf}\PdfEditorKR
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=installer_output
OutputBaseFilename=PdfEditor_Setup_{#AppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes
DisableProgramGroupPage=yes

[Languages]
#ifexist "compiler:Languages\Korean.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로 가기 만들기"; GroupDescription: "추가 작업:"
Name: "openwith"; Description: "PDF 파일 우클릭 '연결 프로그램' 목록에 추가"; GroupDescription: "추가 작업:"

[Files]
Source: "dist\PdfEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; '연결 프로그램' 목록에만 추가 (기본 PDF 프로그램을 강제로 바꾸지 않음)
Root: HKA; Subkey: "Software\Classes\PdfEditorKR.pdf"; ValueType: string; ValueName: ""; ValueData: "PDF 문서"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PdfEditorKR.pdf\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PdfEditorKR.pdf\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PdfEditorKR.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
