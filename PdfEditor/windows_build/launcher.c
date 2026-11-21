// PdfEditor.exe : 내장 파이썬 런타임으로 app\main.py 실행
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR pCmd, int nShow) {
    wchar_t dir[MAX_PATH * 2];
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH * 2);
    if (n == 0) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    wchar_t py[MAX_PATH * 2], script[MAX_PATH * 2];
    BOOL console = wcsstr(pCmd, L"--selftest") != NULL;
    swprintf(py, MAX_PATH * 2, L"%ls\\runtime\\%ls", dir, console ? L"python.exe" : L"pythonw.exe");
    swprintf(script, MAX_PATH * 2, L"%ls\\app\\main.py", dir);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"프로그램 파일이 손상되었습니다. 다시 설치해 주세요.\n(runtime 또는 app 폴더 없음)",
                    L"PDF 편집기", MB_ICONERROR);
        return 2;
    }

    // PATH 에 런타임 DLL 폴더 추가
    static wchar_t path[32768];
    wchar_t old[30000];
    DWORD ol = GetEnvironmentVariableW(L"PATH", old, 30000);
    if (ol == 0 || ol >= 30000) old[0] = 0;
    swprintf(path, 32768, L"%ls\\runtime;%ls\\runtime\\Library\\bin;%ls", dir, dir, old);
    SetEnvironmentVariableW(L"PATH", path);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONHOME", NULL);
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);
    SetEnvironmentVariableW(L"QT_PLUGIN_PATH", NULL);

    static wchar_t cmd[40000];
    swprintf(cmd, 40000, L"\"%ls\" -s \"%ls\" %ls", py, script, pCmd);

    STARTUPINFOW si; PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"프로그램을 시작하지 못했습니다.", L"PDF 편집기", MB_ICONERROR);
        return 3;
    }
    DWORD code = 0;
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
    return (int)code;
}
