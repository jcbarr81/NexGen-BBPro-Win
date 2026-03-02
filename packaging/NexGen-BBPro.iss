; NexGen BBPro installer script for Inno Setup.

[Setup]
AppId={{1e5875ae-6b82-4c87-8172-ceafc7d08661}}
AppName=NexGen BBPro
AppVersion=5.2.0
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
Name: "{app}\images\avatars"; Permissions: users-modify
Name: "{app}\images\parks"; Permissions: users-modify
Name: "{app}\logo\teams"; Permissions: users-modify
Name: "{app}\_internal\config"; Permissions: users-modify
Name: "{app}\_internal\images\avatars"; Permissions: users-modify
Name: "{app}\_internal\images\parks"; Permissions: users-modify
Name: "{app}\_internal\logo\teams"; Permissions: users-modify

[Files]
Source: "..\dist\NexGen-BBPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "NexGen-BBPro.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\NexGen BBPro"; Filename: "{app}\NexGen-BBPro.exe"; WorkingDir: "{app}"; IconFilename: "{app}\NexGen-BBPro.ico"
Name: "{autodesktop}\NexGen BBPro"; Filename: "{app}\NexGen-BBPro.exe"; Tasks: desktopicon; WorkingDir: "{app}"; IconFilename: "{app}\NexGen-BBPro.ico"

[Run]
Filename: "{app}\NexGen-BBPro.exe"; Description: "Launch NexGen BBPro"; Flags: nowait postinstall skipifsilent
Filename: "{app}\_internal\docs\manuals\game_manual_installer.html"; Description: "Open the game manual"; Flags: postinstall shellexec skipifsilent skipifdoesntexist unchecked

[Code]
var
  ExistingUninstallString: string;
  ExistingInstallDir: string;
  InstallModeResolved: Boolean;
  CleanReinstallSelected: Boolean;
  CleanReinstallCompleted: Boolean;

function TrimQuotes(const Value: string): string;
begin
  Result := Trim(Value);
  if (Length(Result) >= 2) and (Result[1] = '"') and (Result[Length(Result)] = '"') then
    Result := Copy(Result, 2, Length(Result) - 2);
end;

function GetInstallLocationFromRegistry(const UninstallKey: string): string;
var
  Value: string;
begin
  if RegQueryStringValue(HKLM, UninstallKey, 'InstallLocation', Value) or
     RegQueryStringValue(HKCU, UninstallKey, 'InstallLocation', Value) then
  begin
    Result := TrimQuotes(Value);
    Exit;
  end;

  if IsWin64 then
  begin
    if RegQueryStringValue(HKLM64, UninstallKey, 'InstallLocation', Value) or
       RegQueryStringValue(HKLM32, UninstallKey, 'InstallLocation', Value) then
    begin
      Result := TrimQuotes(Value);
      Exit;
    end;
  end;

  Result := '';
end;

function TryGetUninstallValue(const UninstallKey: string; var Value: string): Boolean;
begin
  Result :=
    RegQueryStringValue(HKLM, UninstallKey, 'QuietUninstallString', Value) or
    RegQueryStringValue(HKLM, UninstallKey, 'UninstallString', Value) or
    RegQueryStringValue(HKCU, UninstallKey, 'QuietUninstallString', Value) or
    RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', Value);

  if Result then
    Exit;

  if IsWin64 then
  begin
    Result :=
      RegQueryStringValue(HKLM64, UninstallKey, 'QuietUninstallString', Value) or
      RegQueryStringValue(HKLM64, UninstallKey, 'UninstallString', Value) or
      RegQueryStringValue(HKLM32, UninstallKey, 'QuietUninstallString', Value) or
      RegQueryStringValue(HKLM32, UninstallKey, 'UninstallString', Value);
  end;
end;

function GetInstalledUninstallString(): string;
var
  UninstallKeyA: string;
  UninstallKeyB: string;
  UninstallKeyC: string;
  UninstallKeyD: string;
  InstallDir: string;
  UninstallExe: string;
  Value: string;
begin
  UninstallKeyA := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{1e5875ae-6b82-4c87-8172-ceafc7d08661}_is1';
  UninstallKeyB := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{1e5875ae-6b82-4c87-8172-ceafc7d08661}}_is1';
  UninstallKeyC := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\NexGen BBPro_is1';
  UninstallKeyD := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\NexGen-BBPro_is1';

  if TryGetUninstallValue(UninstallKeyA, Value) or
     TryGetUninstallValue(UninstallKeyB, Value) or
     TryGetUninstallValue(UninstallKeyC, Value) or
     TryGetUninstallValue(UninstallKeyD, Value) then
  begin
    Result := Value;
    Exit;
  end;

  InstallDir := GetInstallLocationFromRegistry(UninstallKeyA);
  if InstallDir = '' then
    InstallDir := GetInstallLocationFromRegistry(UninstallKeyB);
  if InstallDir = '' then
    InstallDir := GetInstallLocationFromRegistry(UninstallKeyC);
  if InstallDir = '' then
    InstallDir := GetInstallLocationFromRegistry(UninstallKeyD);

  if InstallDir <> '' then
    UninstallExe := AddBackslash(InstallDir) + 'unins000.exe'
  else
    UninstallExe := '';

  if FileExists(UninstallExe) then
  begin
    Result := '"' + UninstallExe + '"';
    Exit;
  end;

  Result := '';
end;

function ExtractExecutablePath(const CommandLine: string): string;
var
  Text: string;
  EndQuotePos: Integer;
  SpacePos: Integer;
begin
  Text := Trim(CommandLine);
  if Text = '' then
  begin
    Result := '';
    Exit;
  end;

  if Text[1] = '"' then
  begin
    Delete(Text, 1, 1);
    EndQuotePos := Pos('"', Text);
    if EndQuotePos > 0 then
      Result := Copy(Text, 1, EndQuotePos - 1)
    else
      Result := Text;
    Exit;
  end;

  SpacePos := Pos(' ', Text);
  if SpacePos > 0 then
    Result := Copy(Text, 1, SpacePos - 1)
  else
    Result := Text;
end;

function ExtractExecutableParams(const CommandLine: string): string;
var
  Text: string;
  EndQuotePos: Integer;
  SpacePos: Integer;
begin
  Text := Trim(CommandLine);
  if Text = '' then
  begin
    Result := '';
    Exit;
  end;

  if Text[1] = '"' then
  begin
    Delete(Text, 1, 1);
    EndQuotePos := Pos('"', Text);
    if EndQuotePos > 0 then
      Result := Trim(Copy(Text, EndQuotePos + 1, MaxInt))
    else
      Result := '';
    Exit;
  end;

  SpacePos := Pos(' ', Text);
  if SpacePos > 0 then
    Result := Trim(Copy(Text, SpacePos + 1, MaxInt))
  else
    Result := '';
end;

function NormalizeDir(const Value: string): string;
begin
  Result := Trim(Value);
  if Result <> '' then
    Result := RemoveBackslashUnlessRoot(Result);
end;

function BuildUninstallerFromDir(const InstallDir: string): string;
var
  UninsPath: string;
begin
  UninsPath := AddBackslash(InstallDir) + 'unins000.exe';
  if FileExists(UninsPath) then
    Result := '"' + UninsPath + '"'
  else
    Result := '';
end;

function IsInstalledAtDir(const InstallDir: string): Boolean;
var
  AppExePath: string;
begin
  if InstallDir = '' then
  begin
    Result := False;
    Exit;
  end;

  AppExePath := AddBackslash(InstallDir) + 'NexGen-BBPro.exe';
  Result := FileExists(AppExePath) or (BuildUninstallerFromDir(InstallDir) <> '');
end;

function RunExistingUninstaller(): Boolean;
var
  UninstallerPath: string;
  UninstallerParams: string;
  ResultCode: Integer;
begin
  Result := True;
  if ExistingUninstallString = '' then
  begin
    if (ExistingInstallDir <> '') and IsInstalledAtDir(ExistingInstallDir) then
    begin
      MsgBox(
        'Uninstaller entry was not found. Setup will remove the existing install folder directly before reinstalling.',
        mbInformation,
        MB_OK
      );
      if not DelTree(ExistingInstallDir, True, True, True) then
      begin
        MsgBox(
          'Unable to remove existing install folder: ' + ExistingInstallDir + #13#10 +
          'Please remove it manually and run setup again.',
          mbError,
          MB_OK
        );
        Result := False;
      end;
    end;
    Exit;
  end;

  UninstallerPath := ExtractExecutablePath(ExistingUninstallString);
  UninstallerParams := ExtractExecutableParams(ExistingUninstallString);
  if UninstallerPath = '' then
  begin
    MsgBox('Could not detect the existing uninstaller path. Setup will exit.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if UninstallerParams = '' then
    UninstallerParams := '/SILENT /NORESTART'
  else
  begin
    if (Pos('/SILENT', UpperCase(UninstallerParams)) = 0) and
       (Pos('/VERYSILENT', UpperCase(UninstallerParams)) = 0) and
       (Pos('UNINS', UpperCase(ExtractFileName(UninstallerPath))) > 0) then
      UninstallerParams := UninstallerParams + ' /SILENT';
    if Pos('/NORESTART', UpperCase(UninstallerParams)) = 0 then
      UninstallerParams := UninstallerParams + ' /NORESTART';
  end;

  if not Exec(
    UninstallerPath,
    Trim(UninstallerParams),
    '',
    SW_SHOW,
    ewWaitUntilTerminated,
    ResultCode
  ) then
  begin
    MsgBox('Unable to start the existing uninstaller. Setup will exit.', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if ResultCode <> 0 then
  begin
    MsgBox(
      'Uninstall failed (exit code ' + IntToStr(ResultCode) + '). Setup will exit.',
      mbError,
      MB_OK
    );
    Result := False;
  end;
end;

function PromptInstallModeIfNeeded(): Boolean;
var
  Choice: Integer;
  CandidateDir: string;
  PromptText: string;
begin
  Result := True;
  if InstallModeResolved then
    Exit;

  ExistingInstallDir := '';
  ExistingUninstallString := GetInstalledUninstallString();

  CandidateDir := NormalizeDir(WizardDirValue);
  if IsInstalledAtDir(CandidateDir) then
  begin
    ExistingInstallDir := CandidateDir;
    if ExistingUninstallString = '' then
      ExistingUninstallString := BuildUninstallerFromDir(ExistingInstallDir);
  end;

  if (ExistingUninstallString = '') and (ExistingInstallDir = '') then
  begin
    InstallModeResolved := True;
    Exit;
  end;

  if ExistingInstallDir <> '' then
    PromptText :=
      'NexGen BBPro appears to already be installed at:' + #13#10 +
      ExistingInstallDir + #13#10 + #13#10
  else
    PromptText :=
      'NexGen BBPro appears to already be installed.' + #13#10 + #13#10;

  PromptText := PromptText +
    'Yes = Upgrade (overwrite existing files).' + #13#10 +
    'No = Clean reinstall (uninstall old version, then install).' + #13#10 +
    'Cancel = Stop setup.';
  Choice := MsgBox(PromptText, mbConfirmation, MB_YESNOCANCEL);

  if Choice = IDYES then
  begin
    CleanReinstallSelected := False;
    InstallModeResolved := True;
    Exit;
  end;

  if Choice = IDNO then
  begin
    CleanReinstallSelected := True;
    InstallModeResolved := True;
    Exit;
  end;

  Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
    Result := PromptInstallModeIfNeeded();
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if InstallModeResolved then
    Exit;
  if CurPageID = wpInstalling then
    Exit;
  if CurPageID = wpFinished then
    Exit;
  if not PromptInstallModeIfNeeded() then
    WizardForm.Close();
end;

procedure InitializeWizard();
begin
  ExistingUninstallString := '';
  ExistingInstallDir := '';
  InstallModeResolved := False;
  CleanReinstallSelected := False;
  CleanReinstallCompleted := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssInstall then
    Exit;
  if CleanReinstallCompleted then
    Exit;
  if not CleanReinstallSelected then
    Exit;

  if not RunExistingUninstaller() then
    Abort;

  CleanReinstallCompleted := True;
end;




