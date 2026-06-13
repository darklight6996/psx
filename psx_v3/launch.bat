@echo off
title PSX Advisory Agent v3
color 0A
cd /d "%~dp0"
echo.
echo  ================================================
echo   PSX Advisory Agent v3 — Windows Launcher
echo   Local AI Council + Memory Edition
echo  ================================================
echo.

set PYTHON_CMD=python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo  ERROR: Python not found. Install from https://python.org
        echo  Check "Add Python to PATH" during install.
        pause & exit /b 1
    ) else (
        set PYTHON_CMD=py
    )
)
echo  [1/5] Python OK (%PYTHON_CMD%)

if not exist "data\cache" mkdir "data\cache"
echo  [2/5] Directories ready

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo  [NOTE] .env created from template. Edit it to add API keys.
)
echo  [3/5] Config ready

echo  [4/5] Installing/updating dependencies...
%PYTHON_CMD% -m pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 ( echo  ERROR: pip install failed. & pause & exit /b 1 )
echo  [4/5] Dependencies OK

echo  [5/5] Launching...
echo.
echo  App will open at: http://localhost:8501
echo  Press Ctrl+C to stop.
echo.
%PYTHON_CMD% -m streamlit run app.py --server.headless false --browser.gatherUsageStats false
pause
