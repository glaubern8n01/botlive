; Instalador Windows do BotLive - Producao em Massa (Inno Setup 6).
;
; Compile com:  ISCC.exe instalador.iss
; O build-instalador.ps1 faz isso sozinho quando o Inno Setup esta instalado.
;
; O instalador copia SO o executavel e o LEIAME. Nada de .env, token, cookie,
; banco ou sessao: esses nascem na maquina do usuario, na primeira execucao.

#define Nome "BotLive Producao em Massa"
#define Versao "1.0.0"
#define Publicador "BotLive"
#define Executavel "BotLive-Massa.exe"

[Setup]
AppId={{7C1B4E2A-9E3D-4C1F-9C7A-BOTLIVEMASSA01}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher={#Publicador}
DefaultDirName={autopf}\BotLive\ProducaoEmMassa
DefaultGroupName=BotLive
OutputDir=..\dist
OutputBaseFilename=BotLive-Setup-Test
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; autopf + esta linha: instala por usuario se nao houver administrador.
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#Nome}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\{#Executavel}"; DestDir: "{app}"; Flags: ignoreversion
Source: "LEIAME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Executavel}"
Name: "{group}\Desinstalar {#Nome}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\{#Executavel}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Executavel}"; Description: "Abrir agora"; Flags: nowait postinstall skipifsilent

; Desinstalar remove o programa, NUNCA os videos e projetos do usuario:
; eles ficam em %LOCALAPPDATA%\BotLive\massa e continuam la.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
