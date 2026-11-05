; Build only through scripts/build_installer.py: it supplies a verified payload
; inventory, version and a content-addressed application directory.
#if Ver < EncodeVer(6, 7, 4)
  #error Inno Setup 6.7.4 or newer is required.
#endif
#ifndef BundleDir
  #error BundleDir is required. Use scripts/build_installer.py.
#endif
#ifndef MetadataDir
  #error MetadataDir is required. Use scripts/build_installer.py.
#endif
#ifndef AppVersion
  #error AppVersion is required.
#endif
#ifndef AppFileVersion
  #error AppFileVersion is required.
#endif
#ifndef PayloadId
  #error PayloadId is required.
#endif
#ifndef MaxInstallDirUtf16
  #error MaxInstallDirUtf16 is required. Use scripts/build_installer.py.
#endif
#define ProductName "ImmoManager Pro"
#define ProductId "FE5C3565-4782-59C1-9EAC-E3FE6641E286"
#define PayloadSubdir "app\" + PayloadId
#define GuiExe "ImmoManager-Pro.exe"

[Setup]
AppId={{{#ProductId}}
AppName={#ProductName}
AppVersion={#AppVersion}
AppVerName={#ProductName} {#AppVersion}
AppPublisher={#ProductName}
AppPublisherURL=https://github.com/matthiasalexrsr/ImmoManager-Pro
AppSupportURL=https://github.com/matthiasalexrsr/ImmoManager-Pro/issues
AppUpdatesURL=https://github.com/matthiasalexrsr/ImmoManager-Pro/releases
AppComments=Immobilienverwaltung für Windows
VersionInfoVersion={#AppFileVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductVersion={#AppFileVersion}
VersionInfoProductTextVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\ImmoManagerPro
DefaultGroupName={#ProductName}
; Keep Inno's /GROUP initialization enabled. Hide only the visual page below.
DisableProgramGroupPage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
AllowNetworkDrive=no
AllowUNCPath=no
WizardStyle=modern dynamic windows11
WizardSizePercent=120,120
WizardImageFile=wizard-brand.png
WizardImageBackColor=$393E18
WizardSmallImageFile=wizard-mark.png
WizardSmallImageBackColor=clNone
SetupIconFile=..\..\assets\immomanager.ico
UninstallDisplayIcon={app}\{#PayloadSubdir}\{#GuiExe}
UninstallDisplayName={#ProductName}
Uninstallable=yes
AppMutex=Local\ImmoManagerPro.Desktop
SetupMutex=Local\ImmoManagerPro.Setup
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
ChangesAssociations=no
ChangesEnvironment=no
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no
DisableFinishedPage=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
SetupLogging=yes
UninstallLogging=yes
Compression=lzma2/normal
SolidCompression=yes
OutputBaseFilename=ImmoManager-Pro-{#AppVersion}-Setup-x64
OutputDir=..\..\dist\installers

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
german.WelcomeLabel1=Willkommen bei ImmoManager Pro
german.WelcomeLabel2=Ihre Immobilienverwaltung. Klar organisiert.%n%nDieser Assistent installiert ImmoManager Pro für Ihr Windows-Benutzerkonto.%n%nVorhandene Immobilien, Dokumente und Einstellungen bleiben bei einer Aktualisierung erhalten.
german.SelectDirDesc=Wo soll ImmoManager Pro installiert werden?
german.SelectDirLabel3=Hier werden die Programmdateien installiert. Ihre Daten bleiben im persönlichen Datenordner erhalten.
german.SelectTasksDesc=Zusätzliche Verknüpfungen
german.SelectTasksLabel2=Wählen Sie die zusätzlichen Verknüpfungen aus.
german.ReadyLabel1=ImmoManager Pro kann jetzt installiert werden.
german.ReadyLabel2a=Prüfen Sie die Auswahl und klicken Sie auf „Installieren“.
german.FinishedHeadingLabel=ImmoManager Pro ist bereit
german.FinishedLabel=Die Installation wurde erfolgreich abgeschlossen.%n%nÖffnen Sie Ihre Verwaltung oder lernen Sie ImmoManager Pro mit der vorbereiteten Demo Baden-Württemberg kennen.
german.ConfirmUninstall=Möchten Sie ImmoManager Pro und seine Programmdateien entfernen?%n%nIhre Immobilien, Dokumente, Einstellungen und Sicherungen im persönlichen Datenordner bleiben erhalten.
german.UninstalledAll=ImmoManager Pro wurde entfernt.%n%nIhre Daten und Sicherungen wurden nicht gelöscht.

[Tasks]
Name: "desktopicon"; Description: "Verknüpfung auf dem Desktop erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}\{#PayloadSubdir}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MetadataDir}\installation.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MetadataDir}\.immomanager-installation-id"; DestDir: "{app}"; Flags: ignoreversion
Source: "Installationshinweise.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#ProductName}"; Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "{code:GetLaunchArguments}"; WorkingDir: "{app}\{#PayloadSubdir}"; Comment: "Immobilienverwaltung öffnen"; AppUserModelID: "ImmoManagerPro.Desktop"
Name: "{group}\Startmöglichkeiten\Eigenständige Desktop-Anwendung"; Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "--mode standalone"; WorkingDir: "{app}\{#PayloadSubdir}"; AppUserModelID: "ImmoManagerPro.Desktop"
Name: "{group}\Startmöglichkeiten\Im Webbrowser verwenden"; Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "--mode browser"; WorkingDir: "{app}\{#PayloadSubdir}"; AppUserModelID: "ImmoManagerPro.Desktop"
Name: "{group}\Demo\Baden-Württemberg – Desktop"; Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "--mode standalone --demo"; WorkingDir: "{app}\{#PayloadSubdir}"; AppUserModelID: "ImmoManagerPro.Desktop"
Name: "{group}\Demo\Baden-Württemberg – Webbrowser"; Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "--mode browser --demo"; WorkingDir: "{app}\{#PayloadSubdir}"; AppUserModelID: "ImmoManagerPro.Desktop"
Name: "{group}\Installation und Daten"; Filename: "{app}\Installationshinweise.txt"
Name: "{group}\{#ProductName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#ProductName}"; Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "{code:GetLaunchArguments}"; WorkingDir: "{app}\{#PayloadSubdir}"; Tasks: desktopicon; AppUserModelID: "ImmoManagerPro.Desktop"

[Run]
Filename: "{app}\{#PayloadSubdir}\{#GuiExe}"; Parameters: "{code:GetFirstLaunchArguments}"; Description: "{code:GetLaunchDescription}"; Flags: nowait postinstall skipifsilent

[Code]
var
  LaunchModePage: TInputOptionWizardPage;
  FirstWorkspacePage: TInputOptionWizardPage;

function InitializeSetup: Boolean;
var
  RequestedMode, RequestedDemo: String;
begin
  RequestedMode := Lowercase(ExpandConstant('{param:MODE|}'));
  Result := (RequestedMode = '') or (RequestedMode = 'standalone') or (RequestedMode = 'browser');
  if not Result then begin
    Log('Ungültiger Startmodus. /MODE=standalone oder /MODE=browser verwenden.');
    if not WizardSilent then
      MsgBox('Dieser Startmodus ist ungültig. Verwenden Sie /MODE=standalone oder /MODE=browser.', mbError, MB_OK);
  end;
  RequestedDemo := ExpandConstant('{param:DEMO|}');
  if (RequestedDemo <> '') and (RequestedDemo <> '0') and (RequestedDemo <> '1') then begin
    Log('Ungültige Demo-Auswahl. /DEMO=0 oder /DEMO=1 verwenden.');
    if not WizardSilent then
      MsgBox('Diese Demo-Auswahl ist ungültig. Verwenden Sie /DEMO=0 oder /DEMO=1.', mbError, MB_OK);
    Result := False;
  end;
end;

function SelectedLaunchMode: String;
begin
  if LaunchModePage = nil then begin
    Result := 'standalone';
    Exit;
  end;
  if LaunchModePage.SelectedValueIndex = 1 then
    Result := 'browser'
  else
    Result := 'standalone';
end;

function GetLaunchArguments(Param: String): String;
begin
  Result := '--mode ' + SelectedLaunchMode;
end;

function FirstLaunchDemo: Boolean;
begin
  Result := False;
  if FirstWorkspacePage <> nil then Result := FirstWorkspacePage.SelectedValueIndex = 1;
end;

function GetFirstLaunchArguments(Param: String): String;
begin
  Result := GetLaunchArguments(Param);
  if FirstLaunchDemo then Result := Result + ' --demo';
end;

function GetLaunchDescription(Param: String): String;
begin
  if FirstLaunchDemo then
    Result := 'Demo Baden-Württemberg'
  else
    Result := 'ImmoManager Pro';
  if SelectedLaunchMode = 'browser' then
    Result := Result + ' im Webbrowser öffnen'
  else
    Result := Result + ' als Desktop-Anwendung öffnen';
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  { Inno calls this only as part of a completed installation. Selecting a radio
    button or cancelling Setup does not create or modify a user-data folder. }
  SetPreviousData(PreviousDataKey, 'LaunchMode', SelectedLaunchMode);
  if FirstLaunchDemo then
    SetPreviousData(PreviousDataKey, 'FirstLaunchDemo', '1')
  else
    SetPreviousData(PreviousDataKey, 'FirstLaunchDemo', '0');
end;

function GetFileAttributesW(lpFileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function NormalDirectory(const Value: String): String;
begin
  Result := RemoveBackslashUnlessRoot(ExpandFileName(Value));
end;

function AtOrInside(const Child, Parent: String): Boolean;
begin
  Result := CompareText(Copy(AddBackslash(Child), 1, Length(AddBackslash(Parent))), AddBackslash(Parent)) = 0;
end;

function HasReparseParent(Directory: String): Boolean;
var
  Attributes: LongWord;
  Parent: String;
begin
  Result := False;
  while Directory <> '' do begin
    Attributes := GetFileAttributesW(Directory);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then begin
      Result := True;
      Exit;
    end;
    Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Directory));
    if CompareText(Parent, Directory) = 0 then Exit;
    Directory := Parent;
  end;
end;

function IsOwnInstallation(const Directory: String): Boolean;
var
  Marker: AnsiString;
begin
  Result := LoadStringFromFile(AddBackslash(Directory) + '.immomanager-installation-id', Marker);
  if Result then Result := Trim(String(Marker)) = '{#ProductId}';
end;

function NonEmptyDirectory(const Directory: String): Boolean;
var
  Entry: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Directory) + '*', Entry) then begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
          Result := True;
          Exit;
        end;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
end;

function ValidateDirectory(const Value: String): String;
var
  Directory, DataDirectory, DemoDirectory, DriveRoot, RecommendedDirectory: String;
begin
  Result := '';
  Directory := NormalDirectory(Value);
  DataDirectory := NormalDirectory(ExpandConstant('{localappdata}\ImmoManagerPro'));
  DemoDirectory := NormalDirectory(ExpandConstant('{localappdata}\ImmoManagerProDemoBW'));
  DriveRoot := AddBackslash(ExtractFileDrive(Directory));
  if (Directory = '') or (CompareText(Directory, DriveRoot) = 0) then
    Result := 'Bitte wählen Sie einen eigenen Programmordner statt des Laufwerkstamms.'
  else if Length(Directory) > {#MaxInstallDirUtf16} then begin
    Result := 'Der gewählte Programmordner ist zu lang. Bitte wählen Sie einen kürzeren Ordner, damit alle Programmdateien sicher installiert werden können.';
    RecommendedDirectory := NormalDirectory(ExpandConstant('{localappdata}\Programs\ImmoManagerPro'));
    if Length(RecommendedDirectory) <= {#MaxInstallDirUtf16} then
      Result := Result + #13#10#13#10 + 'Empfohlen: ' + RecommendedDirectory;
  end
  else if AtOrInside(Directory, DataDirectory) or AtOrInside(DataDirectory, Directory) or
    AtOrInside(Directory, DemoDirectory) or AtOrInside(DemoDirectory, Directory) then
    Result := 'Programmdateien und persönliche Daten müssen getrennt bleiben. Bitte wählen Sie einen anderen Programmordner.'
  else if HasReparseParent(Directory) then
    Result := 'Bitte wählen Sie einen direkten lokalen Ordner. Ordnerverknüpfungen werden als Installationsziel nicht verwendet.'
  else if DirExists(Directory) and NonEmptyDirectory(Directory) and not IsOwnInstallation(Directory) then
    Result := 'Dieser Ordner enthält bereits andere Dateien. Bitte wählen Sie einen leeren Ordner oder eine vorhandene ImmoManager-Pro-Installation.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Error := ValidateDirectory(WizardDirValue);
    if Error <> '' then begin
      Log('Installationsziel abgewiesen: ' + Error);
      if not WizardSilent then
        MsgBox(Error, mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Disabling this page with the Setup directive also disables /GROUP. Skipping
    navigation here keeps explicit deployment and isolated QA folders effective. }
  Result := PageID = wpSelectProgramGroup;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := ValidateDirectory(WizardDirValue);
  if (Result = '') and CheckForMutexes('Local\ImmoManagerPro.Desktop') then
    Result := 'ImmoManager Pro läuft noch. Beenden Sie die Anwendung und versuchen Sie es anschließend erneut.';
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := 'ImmoManager Pro {#AppVersion}' + NewLine + NewLine + MemoDirInfo;
  Result := Result + NewLine + NewLine + 'Startmodus:' + NewLine + Space;
  if SelectedLaunchMode = 'browser' then
    Result := Result + 'Im Webbrowser verwenden'
  else
    Result := Result + 'Eigenständige Desktop-Anwendung';
  Result := Result + NewLine + NewLine + 'Erster Start:' + NewLine + Space;
  if FirstLaunchDemo then
    Result := Result + 'Demo Baden-Württemberg'
  else
    Result := Result + 'Eigene Verwaltung';
  if MemoGroupInfo <> '' then Result := Result + NewLine + NewLine + MemoGroupInfo;
  if MemoTasksInfo <> '' then Result := Result + NewLine + NewLine + MemoTasksInfo;
  Result := Result + NewLine + NewLine + 'Ihr persönlicher Datenordner:' + NewLine +
    Space + ExpandConstant('{localappdata}\ImmoManagerPro') + NewLine +
    Space + 'Bleibt bei Aktualisierung und Deinstallation erhalten.';
end;

procedure InitializeWizard;
var
  InitialMode, InitialDemo: String;
begin
  WizardForm.BeveledLabel.Caption := 'ImmoManager Pro  ·  {#AppVersion}';
  LaunchModePage := CreateInputOptionPage(wpWelcome, 'Startmodus auswählen',
    'Wie möchten Sie ImmoManager Pro verwenden?',
    'Beide Startmöglichkeiten werden installiert. Sie können später jederzeit über das Startmenü wechseln.', True, False);
  LaunchModePage.Add('Eigenständige Desktop-Anwendung (empfohlen)');
  LaunchModePage.CheckListBox.ItemSubItem[0] := 'Im eigenen Programmfenster arbeiten, ohne einen zusätzlichen Webbrowser.';
  LaunchModePage.Add('Im Webbrowser verwenden');
  LaunchModePage.CheckListBox.ItemSubItem[1] := 'Die Verwaltung wird in Ihrem Standard-Webbrowser geöffnet.';
  InitialMode := Lowercase(ExpandConstant('{param:MODE|}'));
  if InitialMode = '' then InitialMode := GetPreviousData('LaunchMode', 'standalone');
  if InitialMode = 'browser' then
    LaunchModePage.SelectedValueIndex := 1
  else
    LaunchModePage.SelectedValueIndex := 0;
  FirstWorkspacePage := CreateInputOptionPage(LaunchModePage.ID, 'Start nach der Installation',
    'Welche Verwaltung möchten Sie zuerst öffnen?',
    'Beide Verwaltungen sind später über das Startmenü erreichbar.', True, False);
  FirstWorkspacePage.Add('Eigene Verwaltung');
  FirstWorkspacePage.CheckListBox.ItemSubItem[0] := 'Mit Ihren eigenen Objekten beginnen oder Ihre Verwaltung fortsetzen.';
  FirstWorkspacePage.Add('Demo Baden-Württemberg');
  FirstWorkspacePage.CheckListBox.ItemSubItem[1] := 'Eine vorbereitete Verwaltung mit Objekten, Mietern und Dokumenten kennenlernen.';
  InitialDemo := ExpandConstant('{param:DEMO|}');
  if InitialDemo = '' then InitialDemo := GetPreviousData('FirstLaunchDemo', '0');
  if InitialDemo = '1' then
    FirstWorkspacePage.SelectedValueIndex := 1
  else
    FirstWorkspacePage.SelectedValueIndex := 0;
end;
