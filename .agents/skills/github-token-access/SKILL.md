---
name: github-token-access
description: 使用本地存储的 GitHub 访问令牌访问本机用户的 GitHub 账号（woacyh）。当用户要求对 GitHub 进行操作——列出/查看仓库、分析项目代码、创建或修改仓库、更改仓库可见性（公开/私有）、推送源码，或任何需要 GitHub 凭据的 git / REST API 操作时使用。
---

# GitHub 令牌访问

## 概述

本机用户的 GitHub 账号为 **woacyh**（https://github.com/woacyh）。访问凭据已保存在本地，无需用户每次提供令牌。

## 凭据位置

- 令牌文件：`C:\Users\肖宇轩\Documents\Codex\credentials\github_token_backup.txt`
  - 包含完整令牌（"令牌本体"行）、账号、有效期（约 2026-11-10 过期）和使用记录。
- 该令牌也已存入系统 Git 凭证管理器（Windows 凭据库，github.com / woacyh），HTTPS 的 `git clone / push / pull` 会自动使用，无需手工注入。

## 使用方法

### 1. 读取令牌（仅 REST API 需要）

```powershell
$line = Get-Content -Encoding UTF8 "C:\Users\肖宇轩\Documents\Codex\credentials\github_token_backup.txt" | Where-Object { $_ -like "*令牌本体*" }
$env:CODEX_GH_PAT = $line.Split(':')[1].Trim()
```

- 绝不把令牌明文输出到对话、日志或任何仓库文件；如需展示请掩码。
- 用完可清除：`Remove-Item Env:CODEX_GH_PAT`。

### 2. REST API 调用

- 验证连接：`curl.exe -s -H "Authorization: Bearer $env:CODEX_GH_PAT" https://api.github.com/user`
- 列出仓库：`curl.exe -s -H "Authorization: Bearer $env:CODEX_GH_PAT" "https://api.github.com/user/repos?per_page=100&affiliation=owner"`
- 读取仓库文件：`https://raw.githubusercontent.com/woacyh/<仓库>/<分支>/<路径>`（鉴权同上）
- 改为私有仓库：PATCH `https://api.github.com/repos/woacyh/<仓库>`，body 为 `{"private": true}`
  - 注意：PowerShell 直接传 JSON 字符串给 curl 可能报 "Problems parsing JSON"，请改用临时文件：`-d "@payload.json"`。

### 3. Git 操作

- 直接使用 HTTPS 地址 `https://github.com/woacyh/<仓库>.git`，系统凭证管理器会自动提供令牌。
- 若 git 提示需要认证，把令牌写入凭证管理器：

```powershell
@"
protocol=https
host=github.com
username=woacyh
password=<令牌>

"@ | git credential approve
```

### 4. 网络

- GitHub 需要联网；若沙箱拦截，使用 require_escalated 请求授权。

## 注意事项

- 令牌是明文秘密：禁止写入任何 Git 仓库、上传网盘或在聊天中明文展示。
- 若 API 返回 401/403：
  - 令牌可能已过期（90 天有效期，见令牌文件），或已被撤销。
  - 权限不足：改仓库可见性需要令牌含 Administration（Read and write）；读写代码需要 Contents（Read and write）。
  - 处理方式：请用户到 GitHub 重新生成令牌，并同步更新令牌文件与系统凭证管理器。
- 用户要求"上传源码 / 推送 / 查看 GitHub"时，直接使用本技能即可，无需用户再次提供令牌。
