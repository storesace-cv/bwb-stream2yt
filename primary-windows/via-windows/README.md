# Offline Windows Build Kit

These instructions describe how to package and obtain the **stream_to_youtube** headless sender, the **stream2yt-ui** interface, and the **stream2yt-service** Windows service wrapper.

## Download from GitHub (recommended)

Builds run automatically on GitHub Actions (`build-primary-windows.yml`).

| Product | ZIP | Use |
|---------|-----|-----|
| **UI** | `stream2yt-ui-windows-x64.zip` | Operator interface (preview, status, start/stop). Keep the whole extracted folder. |
| **Headless** | `stream-to-youtube-windows-x64.zip` | CLI sender without GUI (`stream_to_youtube.exe`). |
| **Service** | `stream2yt-service-windows-x64.zip` | Windows SCM wrapper (`stream2yt-service.exe`). |

**Artifacts (temporary, 30 days)** — from any successful run (push, pull request, or *Actions → Run workflow*):

1. Open the repository on GitHub → **Actions**.
2. Select **Build primary Windows sender** and open a green run.
3. Download the artifact `stream2yt-windows-x64` (contains the ZIPs + `SHA256SUMS.txt`).

**Releases (permanent)** — when a version tag `v*` is pushed (for example `v2026.07.22`):

1. Open **Releases** on the repository.
2. Download the ZIPs and `SHA256SUMS.txt` attached to that tag.

### Using the UI ZIP on Windows

1. Extract `stream2yt-ui-windows-x64.zip` (you should get a `stream2yt-ui\` folder).
2. Place a valid `.env` inside that folder, next to `stream2yt-ui.exe`.
3. Keep **all** files in the folder together (PySide6 DLLs); do not move only the EXE.
4. Ensure FFmpeg/ffprobe remain at the configured path (default `C:\bwb\ffmpeg\bin\`). FFmpeg is **not** bundled.
5. Run `stream2yt-ui.exe`.

Binaries are **not code-signed**. Windows SmartScreen may warn on first launch; that is expected for unsigned builds.

Do not run a second primary instance while the Windows service (or another EXE) is already streaming.

---

## Local offline build (optional)

### Prerequisites

1. Windows 10 or newer with administrator privileges.
2. Python 3.11.x from <https://www.python.org/downloads/windows/> installed for "All Users" with the "Add python.exe to PATH" option enabled.
3. Local copy of this repository synced to the default path `C:\myapps\bwb-stream2yt\` (or another working directory of your choice).
   - If you still need to download the sources, follow the step-by-step guide in [docs/primary-windows-instalacao.md](../../docs/primary-windows-instalacao.md#11-obter-o-repositorio-git-ou-zip).

### 1. Prepare the virtual environment

```powershell
cd C:\myapps\bwb-stream2yt\primary-windows\via-windows
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> If you prefer to automate the bootstrap process, run `prepare-env.bat` instead of executing the commands manually.

For the service binary locally, also install `pywin32==306` (CI does this automatically).

### 2. Build the executables with PyInstaller

```powershell
# Console launcher (stream_to_youtube.exe)
pyinstaller stream_to_youtube.spec

# Windows service wrapper (stream2yt-service.exe)
pyinstaller stream2yt_service.spec

# UI package (onedir): dist\stream2yt-ui\stream2yt-ui.exe
pyinstaller stream2yt_ui.spec
```

Outputs:

```
primary-windows\via-windows\dist\stream_to_youtube.exe
primary-windows\via-windows\dist\stream2yt-service.exe
primary-windows\via-windows\dist\stream2yt-ui\stream2yt-ui.exe
```

Alternatively, execute `build.bat` to build the headless launcher and the UI package automatically.

### 3. Publish the headless binary (optional)

```powershell
Copy-Item dist\stream_to_youtube.exe C:\myapps\stream_to_youtube.exe -Force
```

### 4. Clean up (optional)

```powershell
Remove-Item -Recurse -Force build .venv
```

---

For additional background on the application, see [`primary-windows/README.md`](../README.md) and [`docs/primary-windows-instalacao.md`](../../docs/primary-windows-instalacao.md).
