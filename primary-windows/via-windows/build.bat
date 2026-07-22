@echo off
setlocal

if not exist .venv (
    echo [error] Virtual environment not found. Run prepare-env.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [build] stream_to_youtube.exe
pyinstaller stream_to_youtube.spec
if %errorlevel% neq 0 (
    echo [error] PyInstaller build failed for stream_to_youtube.
    exit /b %errorlevel%
)

echo [build] stream2yt-ui (onedir)
pyinstaller stream2yt_ui.spec
if %errorlevel% neq 0 (
    echo [error] PyInstaller build failed for stream2yt-ui.
    exit /b %errorlevel%
)

echo [done] Headless binary: %cd%\dist\stream_to_youtube.exe
echo [done] UI folder:       %cd%\dist\stream2yt-ui\stream2yt-ui.exe

endlocal
