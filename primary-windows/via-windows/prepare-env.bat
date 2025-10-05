@echo off
setlocal enabledelayedexpansion

if not exist .venv (
    echo [setup] Creating Python 3.11 virtual environment...
    py -3.11 -m venv .venv
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install --no-warn-script-location -r requirements.txt

endlocal
