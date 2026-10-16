; Windows installer for the manually built UmaTrainerKR.exe.
; Run ISCC from the repository root after PyInstaller has created dist\UmaTrainerKR.exe.
#ifndef AppVersion
  #define AppVersion "0.31.8"
#endif

[Setup]
AppId={{B9FE0794-6DCB-4C25-A2C8-0F4C430D83EC}
AppName=Uma Trainer KR
AppVerName=Uma Trainer KR {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Uma Trainer KR Project
DefaultDirName={localappdata}\Programs\UmaTrainerKR
DefaultGroupName=Uma Trainer KR
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=UmaTrainerKR_Setup_{#AppVersion}
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\UmaTrainerKR_Companion.exe
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 만들기"; GroupDescription: "추가 옵션:"; Flags: unchecked

[Files]
Source: "dist\UmaTrainerKR.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\UmaTrainerKR_Companion.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\UmaTrainerKR_GameTest.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\UmaTrainerKR_Preflight.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Uma Trainer KR"; Filename: "{app}\UmaTrainerKR_Companion.exe"
Name: "{autoprograms}\Uma Trainer KR - 실게임 점검 R22"; Filename: "{app}\UmaTrainerKR_GameTest.exe"
Name: "{autoprograms}\Uma Trainer KR - 오프라인 테스트 R23"; Filename: "{app}\UmaTrainerKR_Preflight.exe"
Name: "{autoprograms}\Uma Trainer KR - 연구/설정"; Filename: "{app}\UmaTrainerKR.exe"
Name: "{autodesktop}\Uma Trainer KR"; Filename: "{app}\UmaTrainerKR_Companion.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\UmaTrainerKR_Companion.exe"; Description: "Uma Trainer KR 실행"; Flags: nowait postinstall skipifsilent
