# Educoder Solver (头歌自动答题与实训接管系统)

基于 Chrome DevTools Protocol (CDP) 挂载物理浏览器与本地 AI 代理接管的头歌（Educoder）自动化答题与编程实训评测系统。

---

## 核心特性

- **真机免密与抗风控**：直接挂载物理 Chrome（9222 调试端口），复用已登录 Cookie 与用户环境，免去账号密码泄露风险，无视验证码与风控限制。
- **Monaco 靶向注入**：通过编辑器原生 API 注入代码，仅替换 `Begin-End` 核心代码区域，注入前自动在 `.cache/backups/` 本地快照备份。
- **单会话复合流水线 (`solve-cycle`)**：单次 CDP 连接内自动流转“弹窗遮罩清理 $\to$ 靶心代码注入 $\to$ 两阶段防竞态评测 $\to$ 高密度 Diff 提纯 $\to$ 自动下一关”，单轮耗时仅 5~8 秒。
- **信息提纯与防熔断**：深度提纯测试集比对结果，过滤 DOM 与 ANSI 杂音；具备连续相同报错主动熔断机制，杜绝死循环消耗评测配额。
- **高鲁棒性工程基线**：内置 88 项全覆盖单元与集成测试（Pytest），全流程保障交互与解析稳定性。

---

## 快速上手

### 1. 环境安装

推荐使用 Python 3.12+ 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 启动物理浏览器

运行内置脚本启动带远程调试端口的 Chrome 浏览器：

```powershell
.\scripts\launch_browser.ps1
```

在打开的浏览器中**登录头歌账号**，并导航至任意实验题目或实训关卡页面。

### 3. 核心命令手册

```powershell
# 1. 探活检测（确认 9222 端口与头歌标签页就绪）
python -m src.cli check-browser

# 2. 感知提取当前关卡题目内容与题型
python -m src.cli dump-question

# 3. 实训编程题：一键复合闭环流转 (注入 -> 评测 -> 提纯回执)
python -m src.cli solve-cycle --code "SELECT * FROM student;" --json

# 4. 客观题快捷作答
python -m src.cli submit-choice --options A,C --json
python -m src.cli submit-blank --answers '["答案1", "答案2"]' --json

# 5. 运行完整测试套件
python -m pytest
```

> **AI 代理调用建议**：与本地大语言模型协同使用时，推荐始终附带 `--json` 参数以获取纯净的结构化输出。

---

## 免责声明

本项目仅供自动化测试、CDP 协议技术研究及本地 AI Agent 交互协同探索使用。请合理使用工具，遵守高校学术诚信规范，严禁用于违规商业代刷或任何违规行为。
