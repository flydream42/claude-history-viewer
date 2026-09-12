@echo off
title Claude History Viewer
echo Starting Claude History Viewer ...
echo If the browser does not open, visit the address shown below.
echo.

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
    echo [ERROR] Python not found. Install Python 3 first
    echo         from https://www.python.org/downloads/
    echo         and check "Add Python to PATH" during setup.
    pause
    exit /b
)

%PYEXE% "%~dp0claude_history_tool.py" %*
