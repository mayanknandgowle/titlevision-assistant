#ifndef MyAppVersion
  #error MyAppVersion must be supplied by the release build
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by the release build
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the release build
#endif

[Setup]
AppId={{C935EF7B-D4B6-4E96-B728-C7DB44A762D1}
AppName=TitleVision Assistant
AppVersion={#MyAppVersion}
AppPublisher=Mayank Nandgowle
AppPublisherURL=https://github.com/mayanknandgowle/titlevision-assistant
AppSupportURL=https://github.com/mayanknandgowle/titlevision-assistant/issues
AppUpdatesURL=https://github.com/mayanknandgowle/titlevision-assistant/releases
DefaultDirName={localappdata}\Programs\TitleVisionAssistant
DefaultGroupName=TitleVision Assistant
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=TitleVisionAssistant-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\TitleVisionAssistant.exe
SetupLogging=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TitleVision Assistant"; Filename: "{app}\TitleVisionAssistant.exe"
Name: "{autodesktop}\TitleVision Assistant"; Filename: "{app}\TitleVisionAssistant.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\TitleVisionAssistant.exe"; Description: "Open TitleVision Assistant"; Flags: nowait postinstall skipifsilent

; User history and browser sessions are outside {app} and retained on uninstall.
