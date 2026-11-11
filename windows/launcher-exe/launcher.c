/* Tiny Windows launcher: runs a PowerShell launcher script that sits next to (or under) this
   .exe with no console window. It exists so the launcher file itself carries the app's icon
   (a .cmd can't have one). Build (mingw):
     x86_64-w64-mingw32-windres icon.rc -O coff -o icon.o
     x86_64-w64-mingw32-gcc -O2 -s -mwindows -municode -DPS1=L"\"...\"" launcher.c icon.o -o X.exe */
#include <windows.h>
#include <wchar.h>

/* -DPYSTART: run python\pythonw.exe start.py (MeetDeck.exe) instead of a PowerShell script */
#if !defined(PS1) && !defined(PYSTART)
#error define PS1 (script path relative to the .exe folder) or PYSTART
#endif

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, LPWSTR args, int show)
{
    wchar_t dir[MAX_PATH], cmd[4 * MAX_PATH];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    wchar_t *slash;
    (void)h; (void)p; (void)args; (void)show;

    if (!GetModuleFileNameW(NULL, dir, MAX_PATH)) return 1;
    slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

#ifdef PYSTART
    _snwprintf(cmd, 4 * MAX_PATH, L"\"%ls\\python\\pythonw.exe\" -X utf8 \"%ls\\start.py\"", dir, dir);
#else
    _snwprintf(cmd, 4 * MAX_PATH,
               L"powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%ls\\%ls\"",
               dir, PS1);
#endif
    cmd[4 * MAX_PATH - 1] = 0;

    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, cmd, L"Couldn't start", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
