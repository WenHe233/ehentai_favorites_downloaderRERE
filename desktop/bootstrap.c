#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    wchar_t root[32768], python[32768], command[65536];
    if (!GetModuleFileNameW(NULL, root, 32768)) return 1;
    wchar_t *separator = wcsrchr(root, L'\\');
    if (!separator) return 1;
    *separator = 0;
    _snwprintf(python, 32768, L"%ls\\runtime\\pythonw.exe", root);
    _snwprintf(command, 65536, L"\"%ls\" \"%ls\\desktop\\launcher.py\" %ls", python, root, arguments);
    SetEnvironmentVariableW(L"EFDRR_RESOURCE_ROOT", root);
    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, root, &startup, &process)) {
        MessageBoxW(NULL, L"程序运行文件不完整，请重新解压整个 ZIP 包。", L"EFDRR", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hProcess);
    return (int)code;
}
