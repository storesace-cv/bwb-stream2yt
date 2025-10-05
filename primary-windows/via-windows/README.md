# Offline Windows Build Kit

These instructions describe how to package the **stream_to_youtube** Windows executable using a fully offline-capable toolchain. The process mirrors the flags and configuration used by the official automation so developers can reproduce the artifact in an isolated Windows workstation.

## Prerequisites

1. Windows 10 or newer with administrator privileges.
2. Python 3.11.x from <https://www.python.org/downloads/windows/> installed for "All Users" with the "Add python.exe to PATH" option enabled.
3. Local copy of this repository synced to the default path `C:\myapps\bwb-stream2yt\` (or another working directory of your choice).
   - If you still need to download the sources, follow the step-by-step guide in [docs/primary-windows-instalacao.md](../../docs/primary-windows-instalacao.md#11-obter-o-repositorio-git-ou-zip).

## 1. Prepare the virtual environment

```powershell
cd C:\myapps\bwb-stream2yt\primary-windows\via-windows
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> 💡 If you prefer to automate the bootstrap process, run `prepare-env.bat` instead of executing the commands manually.

These commands have been validated from the default `C:\myapps\bwb-stream2yt\primary-windows\via-windows` folder layout. You can continue using alternate directory structures as long as you adjust the paths accordingly.

## 2. Build the executable with PyInstaller

With the virtual environment activated, invoke PyInstaller using the provided spec file:

```powershell
pyinstaller stream_to_youtube.spec
```

The spec file already captures the CLI flags we normally pass (`--onefile`, `--noconsole`, hidden imports, and collected binaries). The resulting binary will be written to:

```
primary-windows\via-windows\dist\stream_to_youtube.exe
```

Alternatively, execute `build.bat` to run the same command sequence automatically.

## 3. Publish the binary to the YouTube app directory

Copy the generated executable to the target offline location expected by the Windows primary deployment:

```powershell
Copy-Item dist\stream_to_youtube.exe C:\myapps\stream_to_youtube.exe -Force
```

You can now distribute `C:\myapps\stream_to_youtube.exe` to operators or bundle it with the installation media.

## 4. Clean up (optional)

To reclaim disk space, you may remove the `build\` directory that PyInstaller creates or delete the entire virtual environment:

```powershell
Remove-Item -Recurse -Force build .venv
```

---

For additional background on the application, see [`primary-windows/README.md`](../README.md) and [`docs/primary-windows-instalacao.md`](../../docs/primary-windows-instalacao.md).
