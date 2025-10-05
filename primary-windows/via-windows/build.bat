@echo off
setlocal

if not exist .venv (
    echo [error] Virtual environment not found. Run prepare-env.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

pyinstaller stream_to_youtube.spec

if %errorlevel% neq 0 (
    echo [error] PyInstaller build failed.
    exit /b %errorlevel%
)

echo [done] Binary available at %cd%\dist\stream_to_youtube.exe

endlocal
