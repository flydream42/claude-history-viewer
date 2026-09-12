@echo off
title Build Claude History Viewer EXE
echo ============================================================
echo   Build the tool into a standalone EXE (one time only)
echo ============================================================
echo.

set "PYEXE="
where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
    where py >nul 2>nul && set "PYEXE=py"
)
if not defined PYEXE (
    echo [ERROR] Python not found. Install Python 3 first,
    echo         and check "Add Python to PATH" during setup.
    pause
    exit /b
)

echo [1/3] Regenerating single-file build from source modules ...
%PYEXE% "%~dp0build_single.py"

echo [2/3] Installing PyInstaller ...
%PYEXE% -m pip install --upgrade pyinstaller

echo.
echo [3/3] Building (single file, with console) ...
%PYEXE% -m PyInstaller --onefile --name "ClaudeHistoryViewer" --console "%~dp0claude_history_tool.py"

echo.
echo ============================================================
echo   Done. EXE is at:  dist\ClaudeHistoryViewer.exe
echo   Double-click it to run. No Python needed after this.
echo ============================================================
pause
