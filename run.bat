@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -c "import sys" >nul 2>nul
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -3 -m venv .venv
    )
    if errorlevel 1 (
        echo.
        echo Failed to create the Python virtual environment.
        echo Install Python 3.10 or later and enable "Add Python to PATH".
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe -c "import pynput, pystray, PIL" >nul 2>nul
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Failed to install dependencies. Check the error above and your network connection.
        pause
        exit /b 1
    )
)

.venv\Scripts\python.exe app.py
if errorlevel 1 (
    echo.
    echo The application exited with an error. See the error above.
    pause
)
endlocal
