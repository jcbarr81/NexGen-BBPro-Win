; NexGen BBPro installer script for Inno Setup.

[Setup]
AppId={{1e5875ae-6b82-4c87-8172-ceafc7d08661}}
AppName=NexGen BBPro
AppVersion=7.4.1
AppPublisher=NexGen BBPro
DefaultDirName={commonpf}\NexGen-BBPro
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
const
  CR_CHAR = #13;
  LF_CHAR = #10;
  TAB_CHAR = #9;

var
  ExistingUninstallString: string;
  ExistingInstallDir: string;
  ExistingInstallDetected: Boolean;
  InstallModeResolved: Boolean;
  CleanReinstallSelected: Boolean;
  ResetAdminPasswordOnUpgrade: Boolean;
  CleanReinstallCompleted: Boolean;
  AdminPasswordPage: TInputQueryWizardPage;

function JsonEscape(const Value: string): string;
var
  I: Integer;
  Ch: Char;
begin
  Result := '';
  for I := 1 to Length(Value) do
  begin
    Ch := Value[I];
    case Ch of
      '"': Result := Result + '\"';
      '\': Result := Result + '\\';
      CR_CHAR: Result := Result + '\r';
      LF_CHAR: Result := Result + '\n';
      TAB_CHAR: Result := Result + '\t';
    else
      Result := Result + Ch;
    end;
  end;
end;

function JsonBool(const Value: Boolean): string;
begin
  if Value then
    Result := 'true'
  else
    Result := 'false';
end;

procedure WriteAdminBootstrapToPath(
  const TargetPath, PasswordValue: string;
  const RequireSetup, ResetExistingAdmin: Boolean
);
var
  Payload: string;
begin
  if RequireSetup then
    Payload := '{' + #13#10 +
      '  "require_setup": true,' + #13#10 +
      '  "reset_existing_admin": ' + JsonBool(ResetExistingAdmin) + #13#10 +
      '}'
  else
    Payload := '{' + #13#10 +
      '  "password": "' + JsonEscape(PasswordValue) + '",' + #13#10 +
      '  "require_setup": false,' + #13#10 +
      '  "reset_existing_admin": ' + JsonBool(ResetExistingAdmin) + #13#10 +
      '}';
  SaveStringToFile(TargetPath, Payload, False);
end;

procedure WriteAdminBootstrapFiles();
var
  PasswordValue: string;
  RequireSetup: Boolean;
  ResetExistingAdmin: Boolean;
begin
  if ExistingInstallDetected and (not CleanReinstallSelected) and
     (not ResetAdminPasswordOnUpgrade) then
    Exit;

  RequireSetup := WizardSilent or (AdminPasswordPage = nil);
  ResetExistingAdmin :=
    ExistingInstallDetected and (not CleanReinstallSelected) and
    ResetAdminPasswordOnUpgrade;
  PasswordValue := '';
  if not RequireSetup then
    PasswordValue := Trim(AdminPasswordPage.Values[0]);

  if (not RequireSetup) and (PasswordValue = '') then
    RequireSetup := True;

  WriteAdminBootstrapToPath(
    ExpandConstant('{app}\_internal\data\admin_bootstrap.json'),
    PasswordValue,
    RequireSetup,
    ResetExistingAdmin
  );
  WriteAdminBootstrapToPath(
    ExpandConstant('{app}\data\admin_bootstrap.json'),
    PasswordValue,
    RequireSetup,
    ResetExistingAdmin
  );
end;

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
  ResetChoice: Integer;
begin
  Result := True;
  if InstallModeResolved then
    Exit;

  ExistingInstallDir := '';
  ExistingInstallDetected := False;
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

  ExistingInstallDetected := True;

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
    ResetChoice := MsgBox(
      'Keep the current administrator password for existing leagues?' + #13#10 + #13#10 +
      'Yes = Keep existing admin passwords.' + #13#10 +
      'No = Reset existing admin passwords to the installer password you enter next.',
      mbConfirmation,
      MB_YESNO
    );
    ResetAdminPasswordOnUpgrade := ResetChoice = IDNO;
    InstallModeResolved := True;
    Exit;
  end;

  if Choice = IDNO then
  begin
    CleanReinstallSelected := True;
    ResetAdminPasswordOnUpgrade := False;
    InstallModeResolved := True;
    Exit;
  end;

  Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  PasswordValue: string;
  ConfirmValue: string;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    Result := PromptInstallModeIfNeeded();
    if not Result then
      Exit;
  end;
  if (AdminPasswordPage <> nil) and (CurPageID = AdminPasswordPage.ID) and (not WizardSilent) then
  begin
    PasswordValue := Trim(AdminPasswordPage.Values[0]);
    ConfirmValue := Trim(AdminPasswordPage.Values[1]);
    if PasswordValue = '' then
    begin
      MsgBox(
        'Administrator password is required for interactive installs.',
        mbError,
        MB_OK
      );
      Result := False;
      Exit;
    end;
    if PasswordValue <> ConfirmValue then
    begin
      MsgBox('Administrator passwords do not match.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
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
  ExistingInstallDetected := False;
  InstallModeResolved := False;
  CleanReinstallSelected := False;
  ResetAdminPasswordOnUpgrade := False;
  CleanReinstallCompleted := False;
  AdminPasswordPage := CreateInputQueryPage(
    wpSelectDir,
    'Administrator Password',
    'Set the initial administrator password.',
    'Fresh installs require an administrator password. Upgrades only ask for one when you choose to reset existing admin credentials.'
  );
  AdminPasswordPage.Add('Administrator password:', True);
  AdminPasswordPage.Add('Confirm administrator password:', True);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (AdminPasswordPage = nil) or (PageID <> AdminPasswordPage.ID) then
    Exit;
  if WizardSilent then
  begin
    Result := True;
    Exit;
  end;
  Result :=
    InstallModeResolved and ExistingInstallDetected and
    (not CleanReinstallSelected) and (not ResetAdminPasswordOnUpgrade);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    if CleanReinstallCompleted then
      Exit;
    if not CleanReinstallSelected then
      Exit;

    if not RunExistingUninstaller() then
      Abort;

    CleanReinstallCompleted := True;
    Exit;
  end;

  if CurStep = ssPostInstall then
    WriteAdminBootstrapFiles();
end;




