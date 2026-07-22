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

## Upgrade e teste no Windows

Guia para o primeiro teste funcional da UI numa máquina Windows, sem substituir de imediato a instalação em produção.

### Localização dos ficheiros

Execução GitHub Actions:

https://github.com/storesace-cv/bwb-stream2yt/actions/runs/29944586076

No final da página, em **Artifacts**, descarregar:

`stream2yt-windows-x64`

O download contém:

- `stream2yt-ui-windows-x64.zip`
- `stream-to-youtube-windows-x64.zip`
- `stream2yt-service-windows-x64.zip`
- `SHA256SUMS.txt`

> Nota: a retenção dos artifacts pode ser inferior aos 30 dias indicados no workflow se o repositório tiver um limite global mais curto. Versões permanentes devem ser publicadas depois com uma tag `v*` e GitHub Release.

### Função de cada pacote

| Pacote | Função |
|--------|--------|
| `stream2yt-ui-windows-x64.zip` | Aplicação gráfica. Preview da câmara, Internet, estado do FFmpeg, métricas, erros e botões Iniciar/Parar/Reiniciar. **Testar primeiro.** |
| `stream-to-youtube-windows-x64.zip` | Versão headless, sem interface. Substitui o `stream_to_youtube.exe` antigo apenas se ainda for necessário executar dessa forma. |
| `stream2yt-service-windows-x64.zip` | Serviço Windows para funcionamento automático em segundo plano. Sem interface. A UI e o serviço **não podem** transmitir em simultâneo. |
| `SHA256SUMS.txt` | Hashes SHA-256 para confirmar a integridade dos três ZIPs. |

### Cuidados antes do upgrade

1. Não apagar nem substituir imediatamente a instalação anterior.
2. Fazer backup da pasta atualmente instalada, incluindo:
   - `.env`
   - `stream2yt-service.config.json`, se existir
   - EXEs atuais
   - eventuais ficheiros de configuração locais
3. Não copiar logs nem o ambiente virtual antigo para a nova pasta.
4. Abrir PowerShell como Administrador e parar o serviço:

```powershell
Stop-Service stream2yt-service -ErrorAction SilentlyContinue
```

5. Parar também qualquer `stream_to_youtube.exe` ou `ffmpeg.exe` pertencente à aplicação antiga. Se a versão antiga suportar:

```powershell
.\stream_to_youtube.exe --stop
```

6. Confirmar no Gestor de Tarefas que a aplicação antiga deixou de transmitir.
7. Testar a nova UI numa pasta separada, por exemplo:

`C:\bwb\apps\youtube\stream2yt-ui-test\`

### Instalação da UI

1. Extrair `stream2yt-ui-windows-x64.zip`.
2. Copiar a pasta `stream2yt-ui` completa para:

`C:\bwb\apps\youtube\stream2yt-ui-test\`

3. Não mover apenas `stream2yt-ui.exe`. O EXE precisa da pasta `_internal` e das restantes DLLs.
4. Copiar o `.env` funcional da instalação anterior para:

`C:\bwb\apps\youtube\stream2yt-ui-test\.env`

O `.env` deve ficar ao lado de `stream2yt-ui.exe`.

5. Rever no `.env`: `YT_KEY` ou `YT_URL`, `YT_INPUT_ARGS` ou configuração RTSP, `FFMPEG`, `FFPROBE`, horário de transmissão e endpoint de heartbeat.
6. Confirmar especialmente:

```env
FFMPEG=C:\bwb\ffmpeg\bin\ffmpeg.exe
FFPROBE=C:\bwb\ffmpeg\bin\ffprobe.exe
```

Ajustar se o FFmpeg estiver noutra pasta.

7. Executar:

```powershell
C:\bwb\apps\youtube\stream2yt-ui-test\stream2yt-ui.exe
```

8. Se o SmartScreen aparecer: **Mais informações** → **Executar assim mesmo**. Os binários ainda não estão assinados.

### Teste

Confirmar:

- a janela abre;
- Internet muda para **Ligada** ou **Sem ligação**;
- a imagem da câmara aparece;
- se a câmara falhar, aparece mensagem clara;
- **Iniciar** arranca a transmissão;
- Codificador muda para **A correr**;
- Envio RTMPS passa de **A iniciar** para **A enviar**;
- FPS, bitrate, frames e bytes aumentam;
- **Parar** termina o envio;
- fechar a janela termina o FFmpeg principal e o FFmpeg de preview;
- não ficam processos `ffmpeg.exe` pendurados.

### Importante sobre o serviço

Nesta versão, a UI funciona em modo autónomo e **não** controla uma transmissão já executada pelo serviço.

Para transmitir através da UI: o serviço `stream2yt-service` deve estar parado.

Para voltar a transmitir através do serviço: fechar a UI e executar:

```powershell
Start-Service stream2yt-service
```

Se o serviço estiver ativo, a UI pode abrir, mas não deve conseguir iniciar uma segunda transmissão.

### Upgrade da versão headless

Só substituir `stream_to_youtube.exe` depois de o parar.

1. Fazer backup do EXE antigo.
2. Extrair `stream-to-youtube-windows-x64.zip`.
3. Copiar o novo `stream_to_youtube.exe` para a mesma pasta onde estava o anterior.
4. Manter o `.env` existente.
5. Testar o arranque e a paragem.

### Upgrade do serviço

Só fazer depois do teste da UI.

```powershell
Stop-Service stream2yt-service
```

1. Fazer backup do `stream2yt-service.exe` antigo.
2. Substituir pelo novo `stream2yt-service.exe` no mesmo caminho. Não mudar o caminho do EXE sem reinstalar o serviço.
3. Manter `.env` e `stream2yt-service.config.json`.
4. Arrancar e verificar:

```powershell
Start-Service stream2yt-service
Get-Service stream2yt-service
```

### Rollback

Se a nova versão falhar:

1. Fechar a UI.
2. Parar processos `ffmpeg.exe` iniciados por ela.
3. Parar o serviço, se estiver ativo.
4. Restaurar o EXE ou pasta anterior a partir do backup.
5. Restaurar o `.env` anterior.
6. Arrancar novamente o serviço antigo:

```powershell
Start-Service stream2yt-service
```

Não criar tag nem Release antes de concluir este teste com sucesso.

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
