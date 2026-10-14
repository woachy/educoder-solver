# Educoder Solver (头歌自动答题与实训接管系统)

基于 Chrome DevTools Protocol (CDP) 挂载物理浏览器与本地 AI 代理接管的头歌（Educoder）自动化答题与编程实训评测系统。

---

## 项目背景与目的

在高校计算机实践教学中，在线评测平台（如头歌 Educoder）是日常实验与课程作业的重要载体。然而在实际使用及 AI 协同辅助时，普遍存在以下痛点：
1. **机械搬运繁琐**：平台常限制剪贴板，学生需在本地 IDE、大模型对话框与网页编辑器之间频繁手动切换与粘贴代码；
2. **通用视觉 Agent 适应不良**：基于截图的通用 Computer Use 工具不仅耗时长、Token 成本高昂，且难以在 Monaco 虚拟编辑器中精确定位，极易误删骨架代码；

**本项目旨在构建一套高确定性、轻量低熵的“物理浏览器接管驱动”**，充当本地 AI 大脑的“高精度数字手眼”，实现免密抗风控的题目感知、无损代码靶向注入与自愈评测流转，大幅提升实验效率与排障体验。

---

## 核心特性

- **物理浏览器会话复用**：通过 CDP 挂载运行中的 Chrome 实例（9222 调试端口），复用既有登录态与环境上下文，无需持久化凭据。
- **编辑器深层穿透与状态同步**：探查 React Fiber 节点触发 `onChange` 与 `onSave` 提交（提取 `commitID`），配合快捷键兜底与本地快照备份（`.cache/backups/`），确保代码在评测前落盘并同步至云端。
- **单会话复合流水线 (`solve-cycle`)**：支持在单次连接内连续执行遮罩清理、靶心区域代码注入、控速等待、网络与 DOM 双轨评测监听、差异提纯及关卡流转。
- **拟真控速与跨进程持久化**：基于 `.cache/pacing_state.json` 记录关卡开题时间，跨命令原子扣减已思考时长（配合随机离散抖动与保活心跳），避免高频提交触发审计。
- **作业编排与标签页定向路由**：提供单步原子流（`list-tasks` / `open-task`）与巡航模式；支持根据场景定向路由标签页（`prefer_type`）、自动穿透介绍跳板页并回收冗余关卡标签。
- **结构化感知与空白字符高敏 Diff**：题干表格自动转为 Markdown 紧凑结构；评测比对支持区分实质差异与行尾空白/隐形字符，输出 repr 级差异提示。
- **SPA 加载防抖与白纸题感知**：关卡加载过程防抖等待，自愈瞬态遮罩干扰；针对无模板初始代码场景显式标识 `is_blank_slate`。
- **工程质量与兼容保障**：适配多种 Monaco 编辑器打包形态与容器命名；提供 192 项自动化测试，保障核心交互与提取逻辑稳定。

---

## 快速上手

### 1. 基础环境准备

推荐使用 Python 3.12+ 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 启动物理浏览器并就绪

运行内置脚本启动带远程调试端口的 Chrome 浏览器：

```powershell
.\scripts\launch_browser.ps1
```

在打开的浏览器窗口中**登录头歌账号**，并导航至任意实验题目或实训关卡页面。

---

## AI 协同与自助答题（推荐）

本项目专为本地 AI Agent 打造，无需手动敲打繁琐的作答指令，可直接交由 AI 自助接管：

### 方式一：使用项目自带 Skill（最便捷）

项目内置了标准代理技能规范（位于 `.agents/skills/educoder-solver`）。在支持 Skill 的 AI 编程环境（如 Antigravity / Claude Code / Cursor 等）中，直接向 AI 发送指令：

```text
/educoder-solver 帮我自动完成当前头歌实验关卡
```

AI 将自动完成端口探活、题目结构感知、代码推理、复合注入与自愈流转全过程。

### 方式二：让 AI 阅读手册直接接管

在任意通用 AI 对话中，直接提示 AI 阅读本项目的 Agent 规范或操作手册：

> “请阅读项目中的 `AGENTS.md` 和 `docs/AI_MANUAL.md`，接管 9222 端口的物理浏览器，帮我解答当前头歌题。”

AI 将严格遵循手册中的状态机与两阶段评测 SOP 自主调用底层 CLI 完成答题。

---

## 开发者调试手册（备用）

如需手动调试或排查页面状态，可直接使用统一 CLI：

```powershell
# 1. 探活检测（确认 9222 端口与头歌标签页就绪）
python -m src.cli check-browser

# 2. 结构化提取当前关卡题目内容与题型
python -m src.cli dump-question

# 3. 实训编程题一键闭环流转 (注入 -> 评测 -> 提纯回执)
python -m src.cli solve-cycle --code "SELECT * FROM student;" --json

# 4. 课堂大作业全自动巡航编排 (无人值守推进整门课作业)
python -m src.cli run-classroom-homework --auto-next --json

# 5. 运行全套单元测试
python -m pytest
```

---

## 免责声明

本项目仅供自动化测试、CDP 协议技术研究及本地 AI Agent 交互协同探索使用。请合理使用工具，遵守高校学术诚信规范，严禁用于违规商业代刷或任何违规行为。
