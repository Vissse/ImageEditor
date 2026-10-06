; Inno Setup script for ImageEditor.
; Version comes from the APP_VERSION environment variable (build.ps1 and the
; release workflow set it from core/config.py).
#define MyAppName "ImageEditor"
#define MyAppExeName "ImageEditor.exe"

#define AppVersion GetEnv("APP_VERSION")
#if AppVersion == ""
  #define AppVersion "1.0.0"
#endif

[Setup]
; Fixed AppId: a newer installer recognises the old install and upgrades it in place.
AppId={{6D2C9B1E-5A4F-4E7B-9C3D-1F8A2B7E4D60}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher=Vissse
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Per-user install: no admin prompt, and silent auto-updates need no elevation either.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=icon.ico
OutputDir=Output
OutputBaseFilename=ImageEditor_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Remembered photo folder (QSettings) - removed together with the app.
Root: HKCU; Subkey: "Software\PhotoBatchEditor"; Flags: uninsdeletekey

[Run]
; Normal install: offer "Launch" on the last page.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Silent install (= the in-app update): start the new version again automatically.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: WizardSilent
