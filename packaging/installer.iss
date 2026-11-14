; 深清（Clarity）安装程序（Inno Setup 6）
; 用法：iscc packaging\installer.iss /DAppVersion=0.6.0
; 前置：先运行 PyInstaller（onedir）生成 dist\深清\深清.exe

#ifndef AppVersion
  #define AppVersion "0.21.0"
#endif
#define AppName "深清"
#define AppNameEn "Clarity"
#define AppPublisher "Kryon"
#define AppURL "https://github.com/Kryon2025/Clarity"
#define AppExeName "深清.exe"
#define SourceDir "..\dist\深清"

[Setup]
AppId={{B4E1B8B2-6E4B-4C0E-9A7E-1B8C2D4F6A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} ({#AppNameEn})
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist\installer
OutputBaseFilename=ShenQing-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
; 安装向导：自动跟随系统语言（中文/英文），显示许可证、安装目录与附加任务
ShowLanguageDialog=no
DisableWelcomePage=no
LicenseFile=..\LICENSE
WizardImageFile=installer-assets\wizard.bmp
WizardSmallImageFile=installer-assets\wizard-small.bmp
AppComments=专注与清心：三档专注空间、清番番茄钟、数据统计与主题插件商店。

[Languages]
; 自动按系统界面语言选择：中文系统用中文，其他用英文（ShowLanguageDialog=no 时无语言弹窗）
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinesesimp.CreateDesktopIcon=创建桌面快捷方式
english.CreateDesktopIcon=Create a desktop shortcut
chinesesimp.AutostartTask=开机自动启动（最高权限计划任务）
english.AutostartTask=Start with Windows (highest privileges scheduled task)
chinesesimp.AdditionalTasks=附加任务：
english.AdditionalTasks=Additional tasks:

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalTasks}"; Flags: checkedonce
Name: "autostart"; Description: "{cm:AutostartTask}"; GroupDescription: "{cm:AdditionalTasks}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\NOTICE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\许可证"; Filename: "{app}\LICENSE"
Name: "{group}\第三方组件与素材"; Filename: "{app}\NOTICE"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /TN ""ShenQing.ElevatedAutostart"" /F"; Flags: runhidden; RunOnceId: "RemoveElevatedAutostart"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('autostart') then
      Exec('schtasks.exe',
           '/Create /TN "ShenQing.ElevatedAutostart" /TR "' + ExpandConstant('{app}\' + '{#AppExeName}') + '" /SC ONLOGON /RL HIGHEST /F',
           '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
