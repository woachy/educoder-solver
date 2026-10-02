<#
.SYNOPSIS
    启动用于头歌自动答题系统 CDP 调试的浏览器 (Chrome / Edge)
#>

param (
    [int]$Port = 9222,
    [string]$UserDataDir = "$env:LOCALAPPDATA\EducoderDebugProfile",
    [string]$TargetUrl = "https://www.educoder.net",
    [switch]$NoPause
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "       头歌自动答题系统 - CDP 浏览器启动器       " -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan

# 1. 检查端口是否已被处于 Listen 状态的服务占用
$existingConnection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingConnection) {
    Write-Host "[INFO] 端口 $Port 正在监听 (PID: $($existingConnection[0].OwningProcess))。" -ForegroundColor Yellow
    Write-Host "[OK] 远程调试端口已就绪，可直接在终端运行 python -m src.cli check-browser 或使用 /educoder-solver" -ForegroundColor Green
    exit 0
}

# 2. 候选浏览器路径列表 (优先固定路径)
$candidatePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe"
)

$browserPath = $null
foreach ($path in $candidatePaths) {
    if (Test-Path $path) {
        $browserPath = $path
        break
    }
}

# 2.1 注册表 App Paths 深度探测 (当固定路径未命中时)
if (-not $browserPath) {
    $regKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
    )
    foreach ($regKey in $regKeys) {
        try {
            $regVal = (Get-ItemProperty -Path $regKey -ErrorAction SilentlyContinue).'(default)'
            if ($regVal) {
                $cleanedPath = $regVal.Trim('"', "'")
                if (Test-Path $cleanedPath) {
                    $browserPath = $cleanedPath
                    break
                }
            }
        } catch {
            # 忽略注册表访问异常
        }
    }
}

# 2.2 PATH 环境变量探测
if (-not $browserPath) {
    $cmd = Get-Command chrome, msedge -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source -and (Test-Path $cmd.Source)) {
        $browserPath = $cmd.Source
    }
}

if (-not $browserPath) {
    Write-Host "[ERROR] 未能自动找到 Google Chrome 或 Microsoft Edge，请确认是否已安装。" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] 找到可用浏览器: $browserPath" -ForegroundColor Green
Write-Host "[INFO] 调试端口: $Port" -ForegroundColor Gray
Write-Host "[INFO] 独立用户目录: $UserDataDir" -ForegroundColor Gray
Write-Host "[INFO] 目标网址: $TargetUrl" -ForegroundColor Gray

if (-not (Test-Path $UserDataDir)) {
    New-Item -ItemType Directory -Path $UserDataDir -Force | Out-Null
}

$arguments = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=`"$UserDataDir`"",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
    "`"$TargetUrl`""
)

Write-Host "`n[*] 正在启动独立调试浏览器窗口..." -ForegroundColor Cyan
Start-Process -FilePath $browserPath -ArgumentList $arguments

# 3. 等待并验证端口启动 (轮询最多 8 次，每次 500ms)
Write-Host "[*] 正在等待端口 $Port 开启监听..." -ForegroundColor Cyan
$retries = 8
$started = $false
while ($retries -gt 0) {
    Start-Sleep -Milliseconds 500
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        $started = $true
        break
    }
    $retries--
}

if ($started) {
    Write-Host "`n==================================================" -ForegroundColor Cyan
    Write-Host "[OK] 浏览器已成功在端口 $Port 开启 CDP 远程调试！" -ForegroundColor Green
    Write-Host "`n后续操作指引：" -ForegroundColor Yellow
    Write-Host "1. 请在弹出的浏览器中登录您的头歌账号。" -ForegroundColor White
    Write-Host "2. 进入待作答的具体实验或题目关卡。" -ForegroundColor White
    Write-Host "3. 返回终端运行: python -m src.cli check-browser 或输入 /educoder-solver" -ForegroundColor White
    Write-Host "==================================================" -ForegroundColor Cyan
} else {
    Write-Host "`n==================================================" -ForegroundColor Yellow
    Write-Host "[WARN] 浏览器已尝试唤起，但端口 $Port 暂未检测到 Listen 状态。" -ForegroundColor Yellow
    Write-Host "`n排查建议：" -ForegroundColor Gray
    Write-Host "1. 若当前系统中已有同款浏览器日常进程运行，由于 Chromium 单例机制，" -ForegroundColor Gray
    Write-Host "   可能会重定向到已有进程导致调试端口未能生效。" -ForegroundColor Gray
    Write-Host "   建议：完全关闭当前运行的 Chrome/Edge 窗口后重新执行本脚本。" -ForegroundColor Gray
    Write-Host "2. 检查本机防火墙或杀毒软件是否拦截了 localhost:$Port 端口。" -ForegroundColor Gray
    Write-Host "3. 验证命令: python -m src.cli check-browser" -ForegroundColor Gray
    Write-Host "==================================================" -ForegroundColor Yellow
}
