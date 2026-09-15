@echo off
REM Run Image to Text from source. First run sets up a local virtual
REM environment in .venv and installs what the app needs.
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Could not create a virtual environment.
        echo Install Python 3.9 or newer from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed.
        pause
        exit /b 1
    )
)

REM pythonw.exe keeps the console window from sitting behind the app.
set "PYTHONPATH=%~dp0src"
start "" ".venv\Scripts\pythonw.exe" -m image_to_text %*

endlocal
