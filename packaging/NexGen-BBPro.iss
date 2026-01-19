; NexGen BBPro installer script for Inno Setup.

[Setup]
AppId={{1e5875ae-6b82-4c87-8172-ceafc7d08661}}
AppName=NexGen BBPro
AppVersion=4.3.1
AppPublisher=NexGen BBPro
DefaultDirName={pf}\NexGen-BBPro
DefaultGroupName=NexGen BBPro
UninstallDisplayIcon={app}\NexGen-BBPro.exe
SetupIconFile=NexGen-BBPro.ico
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=NexGen-BBPro-Setup
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked

[Dirs]
Name: "{app}\config"; Permissions: users-modify
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\images\avatars"; Permissions: users-modify
Name: "{app}\images\parks"; Permissions: users-modify
Name: "{app}\logo\teams"; Permissions: users-modify
Name: "{app}\_internal\config"; Permissions: users-modify
Name: "{app}\_internal\data"; Permissions: users-modify
Name: "{app}\_internal\images\avatars"; Permissions: users-modify
Name: "{app}\_internal\images\parks"; Permissions: users-modify
Name: "{app}\_internal\logo\teams"; Permissions: users-modify

[Files]
Source: "..\dist\NexGen-BBPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "NexGen-BBPro.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\NexGen BBPro"; Filename: "{app}\NexGen-BBPro.exe"; WorkingDir: "{app}"; IconFilename: "{app}\NexGen-BBPro.ico"
Name: "{autodesktop}\NexGen BBPro"; Filename: "{app}\NexGen-BBPro.exe"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\NexGen-BBPro.ico"
