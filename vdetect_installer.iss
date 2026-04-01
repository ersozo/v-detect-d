; Inno Setup Script for V-Detect
#define MyAppName "V-Detect"
#define MyAppVersion "1.0.0" ; This should be synced with VERSION from backend/version.py
#define MyAppPublisher "Özgür Ersöz"
#define MyAppExeName "VDetect.exe"

[Setup]
AppId={{6BF712F4-E089-471B-B0D0-66685E0A861A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
SetupIconFile=desktop\ui\assets\icon.ico
DisableProgramGroupPage=yes
OutputBaseFilename=VDetect_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Source should match the 'dist/VDetect' directory created by PyInstaller
Source: "dist\VDetect\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Include icon for installer/shortcuts reference
Source: "desktop\ui\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up appdata folder optionally (uncomment for full wipe)
; Type: filesandordirs; Name: "{userappdata}\VDetect"
