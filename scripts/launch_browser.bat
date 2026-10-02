@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ==================================================
echo        头歌自动答题系统 - CDP 浏览器启动器
echo ==================================================

set "PORT=9222"
set "USER_DATA_DIR=%LOCALAPPDATA%\EducoderDebugProfile"
set "TARGET_URL=https://www.educoder.net"
set "EXIT_CODE=0"

REM 1. 检查端口是否已被处于 LISTENING 状态的服务占用
netstat -ano 2>nul | findstr /C:":%PORT% " | findstr /I "LISTENING" >nul
if !ERRORLEVEL! equ 0 (
    echo [INFO] 端口 %PORT% 已处于监听状态，远程调试服务已经在运行中。
    echo [OK] 可直接在终端运行: python -m src.cli check-browser 或在对话框输入 /educoder-solver
    set "EXIT_CODE=0"
    goto :EXIT_SCRIPT
)

REM 2. 探测 Chrome 和 Edge 路径
set "BROWSER_PATH="
set "BROWSER_NAME="

REM 2.1 静态路径检测 (单行无括号语法，免疫 ProgramFiles(x86) 括号解析陷阱)
if not defined BROWSER_PATH if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
    set "BROWSER_NAME=Google Chrome"
)
if not defined BROWSER_PATH if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
    set "BROWSER_NAME=Google Chrome"
)
if not defined BROWSER_PATH if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
    set "BROWSER_PATH=%LocalAppData%\Google\Chrome\Application\chrome.exe"
    set "BROWSER_NAME=Google Chrome"
)
if not defined BROWSER_PATH if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
    set "BROWSER_NAME=Microsoft Edge"
)
if not defined BROWSER_PATH if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
    set "BROWSER_NAME=Microsoft Edge"
)
if not defined BROWSER_PATH if exist "%LocalAppData%\Microsoft\Edge\Application\msedge.exe" (
    set "BROWSER_PATH=%LocalAppData%\Microsoft\Edge\Application\msedge.exe"
    set "BROWSER_NAME=Microsoft Edge"
)

REM 2.2 注册表 App Paths 深度探测 (HKLM 与 HKCU)
if not defined BROWSER_PATH call :QUERY_REG "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" "Google Chrome (Registry)"
if not defined BROWSER_PATH call :QUERY_REG "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" "Google Chrome (User Registry)"
if not defined BROWSER_PATH call :QUERY_REG "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe" "Microsoft Edge (Registry)"
if not defined BROWSER_PATH call :QUERY_REG "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe" "Microsoft Edge (User Registry)"

REM 2.3 校验探测结果
if not defined BROWSER_PATH (
    echo [ERROR] 未能在本机找到 Google Chrome 或 Microsoft Edge，请确认是否已安装。
    echo 检查位置包括: 默认安装目录、本地用户目录以及系统注册表 App Paths。
    set "EXIT_CODE=1"
    goto :EXIT_SCRIPT
)

echo [INFO] 成功探测到可用浏览器: !BROWSER_NAME!
echo [INFO] 浏览器可执行文件路径: "!BROWSER_PATH!"
echo [INFO] 远程调试监听目标端口: %PORT%
echo [INFO] 独立用户调试数据目录: !USER_DATA_DIR!
echo [INFO] 初始自动加载登录网址: %TARGET_URL%

REM 3. 确保用户数据目录存在
if not exist "!USER_DATA_DIR!" (
    mkdir "!USER_DATA_DIR!" 2>nul
)

REM 4. 唤起独立浏览器调试窗口
echo.
echo [*] 正在拉起独立调试浏览器窗口，请稍候...
start "" "!BROWSER_PATH!" --remote-debugging-port=%PORT% --user-data-dir="!USER_DATA_DIR!" --no-first-run --no-default-browser-check --remote-allow-origins=* "%TARGET_URL%"

REM 5. 轮询检测端口绑定状态 (最多等待 8 秒)
echo [*] 正在等待浏览器完成端口 %PORT% 绑定...
set "PORT_READY=0"
for /L %%c in (1,1,8) do (
    if !PORT_READY! equ 0 (
        ping 127.0.0.1 -n 2 >nul 2>&1
        netstat -ano 2>nul | findstr /C:":%PORT% " | findstr /I "LISTENING" >nul
        if !ERRORLEVEL! equ 0 (
            set "PORT_READY=1"
        )
    )
)

REM 6. 输出结果与指引
if !PORT_READY! equ 1 (
    echo.
    echo ==================================================
    echo [OK] 浏览器已成功拉起，并在端口 %PORT% 开启远程调试！
    echo.
    echo 后续操作指引：
    echo 1. 请在弹出的新浏览器窗口中登录您的头歌账号。
    echo 2. 进入待作答的具体实验或题目关卡。
    echo 3. 返回 AI 对话框输入: /educoder-solver 帮我答题
    echo ==================================================
    set "EXIT_CODE=0"
) else (
    echo.
    echo ==================================================
    echo [WARN] 浏览器进程已尝试唤起，但端口 %PORT% 在 8 秒内未检测到 LISTENING 监听。
    echo.
    echo 排查排障建议：
    echo 1. 若当前系统中已有同款浏览器日常进程运行，由于 Chromium 单例机制，
    echo    可能会重定向到已有进程导致调试端口未能生效。
    echo    建议：完全关闭当前运行的 Chrome/Edge 窗口后重新双击本脚本。
    echo 2. 检查本机防火墙或杀毒软件是否拦截了 localhost:%PORT% 端口。
    echo 3. 验证命令: python -m src.cli check-browser
    echo ==================================================
    set "EXIT_CODE=2"
)

:EXIT_SCRIPT
echo.
echo 按任意键退出本提示窗口 - 浏览器将保持在后台运行 ...
pause >nul
exit /b !EXIT_CODE!

REM 子过程：注册表查询
:QUERY_REG
for /f "tokens=1,2*" %%i in ('reg query %1 /ve 2^>nul') do (
    if /i "%%j"=="REG_SZ" (
        set "TEMP_PATH=%%k"
        set "TEMP_PATH=!TEMP_PATH:"=!"
        if exist "!TEMP_PATH!" (
            set "BROWSER_PATH=!TEMP_PATH!"
            set "BROWSER_NAME=%~2"
        )
    )
)
goto :EOF
