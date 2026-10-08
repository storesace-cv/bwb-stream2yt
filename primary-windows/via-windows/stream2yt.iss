; Inno Setup — stream2yt (A+B)
; O pipeline CI prepara dist\ e staging\bin (FFmpeg + GStreamer + auxiliar)
; antes de invocar ISCC. Downloads no cliente usam PowerShell (sem Python/pip).

#define MyAppName "stream2yt"
#define MyAppVersion "2026.10.08.1"
#define MyAppPublisher "BWB"
#define InstallRoot "C:\bwb\apps\youtube"
#define BinDir "{#InstallRoot}\bin"
#define DataDir "{#InstallRoot}\data"
#define CacheDir "{#InstallRoot}\installer-cache"

[Setup]
AppId={{A7C2E8F1-4B5D-4E9A-9C31-8F0D2B6E1A90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={#InstallRoot}
DisableDirPage=yes
DefaultGroupName={#MyAppName}
OutputDir=..\..\release
OutputBaseFilename=stream2yt-setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartIfNeededByRun=no
UninstallDisplayName={#MyAppName}
; Update/repair preserva DataDir (config/chave) por defeito.

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Files]
; Aplicação
Source: "..\..\dist\stream2yt-ui\*"; DestDir: "{app}\ui"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\dist\stream_to_youtube.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\stream2yt-service.exe"; DestDir: "{app}"; Flags: ignoreversion
; Auxiliar GStreamer (PyInstaller) — sem Python no cliente
Source: "..\..\dist\gst_rtmps_helper.exe"; DestDir: "{#BinDir}"; Flags: ignoreversion
; Runtime FFmpeg + GStreamer pré-verificados no CI (pacote offline)
Source: "..\..\staging\bin\ffmpeg\*"; DestDir: "{#BinDir}\ffmpeg"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\staging\bin\gstreamer\*"; DestDir: "{#BinDir}\gstreamer"; Flags: ignoreversion recursesubdirs createallsubdirs
; Scripts de install/repair (PowerShell nativo)
Source: "installer\*"; DestDir: "{app}\installer"; Excludes: "__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs
; Cache offline dos pacotes originais (repair/re-hash)
Source: "..\..\staging\installer-cache\*"; DestDir: "{#CacheDir}"; Flags: ignoreversion

[Dirs]
Name: "{#DataDir}"; Permissions: admins-full
Name: "{#BinDir}"; Permissions: admins-full
Name: "{#CacheDir}"; Permissions: admins-full

[Icons]
Name: "{group}\stream2yt UI"; Filename: "{app}\ui\stream2yt-ui.exe"
Name: "{commondesktop}\stream2yt"; Filename: "{app}\ui\stream2yt-ui.exe"

[Run]
; ACLs — não inicia transmissão nem serviço de envio
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\secure_data_dir.ps1"" -DataDir ""{#DataDir}"" -BinDir ""{#BinDir}"""; \
  StatusMsg: "A aplicar ACLs…"; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\verify_runtime.ps1"" -BinDir ""{#BinDir}"" -DataDir ""{#DataDir}"" -RequireGStreamer -HelperPath ""{#BinDir}\gst_rtmps_helper.exe"""; \
  StatusMsg: "A verificar runtime…"; Flags: runhidden waituntilterminated
; UI opcional — sem arranque automático do serviço de streaming
Filename: "{app}\ui\stream2yt-ui.exe"; Description: "Abrir stream2yt"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\ui"
Type: files; Name: "{app}\stream_to_youtube.exe"
Type: files; Name: "{app}\stream2yt-service.exe"
Type: filesandordirs; Name: "{app}\installer"
Type: filesandordirs; Name: "{#BinDir}"
; Preservar {#DataDir} e chaves por defeito.

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { Não iniciar o serviço de transmissão durante a instalação. }
  Result := '';
end;
