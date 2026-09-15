@echo off
REM Build a single-file ImageToText.exe into dist\.
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create a virtual environment.
        echo Install Python 3.9 or newer from https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

set "PY=.venv\Scripts\python.exe"

echo Installing build dependencies...
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements-dev.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo Running tests...
"%PY%" -m pytest
if errorlevel 1 (
    echo.
    echo Tests failed - not building. Fix them, or pass /force to skip this check.
    if /i not "%~1"=="/force" (
        pause
        exit /b 1
    )
)

echo.
echo Building ImageToText.exe...
"%PY%" -m PyInstaller --noconfirm --clean packaging\ImageToText.spec
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Done. The app is at: %~dp0dist\ImageToText.exe
echo It is self-contained - copy it anywhere, no install needed.
pause

endlocal
