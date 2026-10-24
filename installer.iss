; 游戏助手 安装脚本（Inno Setup 6）
; 按用户安装，不需要管理员权限；卸载时删除整个安装目录。

#define AppName "游戏助手"
#define AppVersion "1.0.0"
#define AppExe "GameAssistant.exe"

[Setup]
AppId={{B3F1A9E2-7C4D-4A61-9F8E-2D5C7B1A6E30}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\GameAssistant
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer\output
OutputBaseFilename=GameAssistant-Setup-{#AppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
VersionInfoVersion=1.0.0.0
VersionInfoCompany=GameAssistant
VersionInfoDescription={#AppName} 安装程序

[Languages]
Name: "zh"; MessagesFile: "installer\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce
Name: "startup"; Description: "开机自动启动"; GroupDescription: "附加任务："

[Files]
; 不打包 settings.json：升级不会覆盖用户配置，全新安装则由首启向导来问
Source: "dist\GameAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config\settings.json,data\*"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GameAssistant"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"