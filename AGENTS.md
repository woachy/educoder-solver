# AGENTS.md - 头歌自动答题系统规范与行为准则

## 1. 项目定位与技术栈 (Project & Stack)
- **项目目标**：通过本地 CDP (Chrome DevTools Protocol) 挂载物理浏览器接管头歌平台，由本地 AI 代理直接闭环进行“感知-推理-控速-答题-自愈-巡航”，严禁依赖外部付费 API。
- **技术栈**：Python 3.12+ / Playwright (CDP Remote Debugging) / BeautifulSoup4 / Rich / Argparse / Pytest
- **架构版本**：v3.0.0 (支持 Pacing 思考控速防秒刷、Classroom Orchestrator 课堂作业自动化巡航、题干表格 Markdown 结构化、CDP 网络层评测拦截与 Monaco 深度 Fiber 穿透)
- **依赖管理**：推荐使用专用 venv (`.venv`) 与 `pip`。

## 2. 核心指令 (Core Commands)
- **环境初始化**：`python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt`
- **Playwright 安装**：`playwright install chromium`（仅备用，主流程挂载本机 9222 端口无需下载大浏览器）
- **浏览器端口探针**：`python -m src.cli check-browser`
- **页面检测与题目提取**：`python -m src.cli dump-question`
- **课堂大作业推进 (双模式支持)**：
  - **模式 1 (AI Agent 单步原子流，短连接 Agent 强烈首选)**：
    - 列表只读扫描：`python -m src.cli list-tasks [--match <keyword>] --json`
    - 单步开启大题：`python -m src.cli open-task [--index <N>] [--match <keyword>] --json`
    - 关卡闭环作答：`python -m src.cli solve-cycle --code "<target_code>" [--file <path>] --auto-next [--min-duration 60] --json`
  - **模式 2 (长连接双向协程流，带 30s 超时保护)**：
    - 交互式全自动巡航：`python -m src.cli run-classroom-homework [--max-tasks 10] [--min-duration 60] [--dry-run] [--interactive] [--match <keyword>] --json`
- **单关复合闭环流水线 (实训单题首选)**：`python -m src.cli solve-cycle --code "<target_code>" [--file <path>] [--full] [--auto-next] [--min-duration 60] --json`
- **分步下发答题动作**：
  - 客观题：`python -m src.cli submit-choice --options A,C --json`
  - 填空题：`python -m src.cli submit-blank --answers '["答案1", "答案2"]' --json`
  - 代码注入：`python -m src.cli inject-code --code "<code_str>" --json`
  - 评测监听：`python -m src.cli trigger-eval [--timeout 60] [--auto-next] --json`
  - 统一入口：`python -m src.cli submit-answer --type [choice|blank|code] --data <json_or_file>`
- **自动化测试**：`python -m pytest`
- **代码静态检查**：`python -m flake8 src/` 或 `python -m ruff check src/`

## 3. 行为边界 (Three-Tier Boundaries)

### Always do (强制执行)
- **端口前置探活**：任何浏览器操作前，必须校验 `localhost:9222` 可达性，如未开启提示用户运行启动脚本。
- **课堂大作业官方命令链准则**：在面对整门课作业列表页面时，**必须使用官方命令链推进**：一问一答型短连接 AI Agent 优先使用单步原子流（`list-tasks` 扫描列表 -> `open-task` 激活新 Tab -> `dump-question` 感知题目 -> `solve-cycle` 闭环做题）；具备实时双向 stdio 管道的外部进程方可使用 `run-classroom-homework --interactive`。
- **防秒刷控速硬性规范 (Anti-Cheat Pacing)**：严禁单关卡毫秒级秒刷触发教师端审查与平台风控！单关提交必须经过智能控速（默认 `--min-duration 60` 配合 `5~20s` 拟真离散抖动）。底层通过开题打卡机制智能计算差额并补足，等待期间注入微滚动保活心跳（每 15s），本地快速自测或用户明确要求极速时方可传 `0`。
- **实训优先复合流水线**：实训题作答优先使用 `solve-cycle` 单次会话流水线，将“弹窗清理-Monaco穿透注入-控速等待-网络层/DOM双轨评测-Diff提纯-流转”收敛在单次 CDP 进程内，杜绝多次进程冷启动开销。
- **题干表格结构化与低熵多模态准则**：遇到页面中的 `<table>` 必须通过 `table_to_markdown` 转为紧凑的 Markdown 表格嵌入题干，图片仅保留结构化引用（如 `[附图说明: xxx]`），严禁向大模型吐出未经清洗的大段 base64 乱码或原始 HTML 噪音。
- **保留 `\d+S` 倒计时与 `_has_real_result` 语义过滤**：触发评测后必须严格识别按钮倒计时文本（如 `\d+S`、`评测中`），并在快照比对中过滤“平台会对你编写的代码进行测试”等初始占位符，必须确认出现实质性评测结论（`_has_real_result`），严禁在倒计时冷却期或旧占位状态下提前误判通关。
- **弹窗与遮罩自动清理**：在执行代码注入或评测交互前，必须调用 `dismiss_blocking_overlays` 自动清除过关庆祝弹窗及阻断鼠标事件的残留遮罩（pointer-events: none / display: none）。
- **只读最小侵入**：默认通过 DOM 查询提取题目，除非必要不注入破坏性脚本；执行代码写入前必须自动进行本地持久化快照备份（`.cache/backups/`）。
- **真实拟真延迟**：选择题点击与代码提交间必须加入随机微延迟（0.5s - 1.5s），禁止机器级并发连点触发防刷风控。
- **结构化 JSON 输出**：CLI 工具对外输出必须保持格式整洁的 JSON，便于 AI Agent 无损解析并推演。
- **文档与 Skill 多端强一致性同步规范 (Documentation & Skill Sync)**：凡涉及 CLI 命令变动、参数增删、核心工作流演化（如单步原子流、超时保护）或解题机制升级时，**必须同步更新全部相关文档与 Skill 资产**。包括：
  1. 面向 AI 的操作手册：`docs/AI_MANUAL.md`（参数契约、握手协议与排障对照表）；
  2. 工程内部专属 Skill：`.agents/skills/educoder-solver/SKILL.md` 及其内部附录 `.agents/skills/educoder-solver/references/ai_manual.md`；
  3. 多端宿主全局 Skill 库：同步覆盖至 Antigravity 全局技能库（`~/.gemini/config/skills/educoder-solver/`）与 Codex 全局技能库（`~/.codex/skills/educoder-solver/`）；
  4. 提交版本库时，文档与 Skill 资产必须一并纳入 Git 提交。
- **测试通过再交付**：代码修改后必须执行全套测试（`pytest`），全绿通过方可交付，禁止提交带有未捕获异常的代码。

### Ask first (变更前确认)
- **高危破坏性操作**：需要清空编辑器已有代码、强制重置关卡或覆盖用户本地环境配置时，必须先征得用户确认。
- **引入庞大依赖**：引入除轻量网络/解析/CLI 之外的新重型库（如 Selenium、庞大视觉框架）前，需说明必要性并确认。

### Never do (绝对红线)
- **严禁代码与文档 Skill 脱节交付**：严禁在更新了核心 CLI 接口或工作流规范后，遗漏对 `docs/AI_MANUAL.md`、`SKILL.md`（含附录 `references/ai_manual.md`）及宿主全局 Skill 库的同步更新，防止后续 AI Agent 读取过时契约导致交互死锁或空跑。
- **严禁向大模型吐出未经清洗的大段 DOM/HTML 杂音**：严禁将原始网页树、内联样式、base64 图片数据、第三方脚本或未解析的 DOM 源码塞入上下文，防止污染 AI 心智带宽。
- **严禁直接秒刷导致被教师端审计**：禁止在生产环境关卡绕过思考控速机制以低于 5 秒的时长连刷通关。
- **严禁私自编写临时 Python 脚本切换 Tab 或操作题目**：严禁在项目根目录或 `.cache/` 临时生成 `.py` 脚本来执行浏览器操作，所有列表扫描、大题开启、代码注入、关卡评测必须全部使用官方 CLI 子命令。
- **严禁引入第三方商业大模型 API**：禁止任何添加外部商用 API Key（如 OpenAI / Claude API）的要求，决策大脑由本地 AI 担当。
- **严禁硬编码用户凭证**：不得在代码中存储用户名、密码或 Token，会话完全复用物理浏览器已有 Cookie。
- **严禁盲目死循环评测**：若连续 3 次评测报错未发生变化，必须停止触发“评测”按钮并向用户发出告警，严禁无限消耗平台评测配额。

## 4. 关键代码范式 (Code Patterns)
- **单步大题推进 (Atomic Step Orchestration)**：通过 `list_classroom_tasks(page)` 安全只读扫描卡片 -> `open_classroom_task(page, index)` 点击并捕获切换新 Tab -> 关卡内调用 `run_solve_cycle()` 循环推进。
- **课堂作业自动化巡航 (Classroom Cruise)**：通过 `run_classroom_cruise()` 调度 `scan_classroom_tasks -> expect_page -> solve_cycle -> close_task_page -> reload_list`，配合 30s stdin 超时看门狗，实现无人值守自动推进。
- **单会话复合答题流水线 (Solve Cycle)**：通过 `run_solve_cycle()` 在同一个页面生命周期内串联 `ModalSweeper -> inject_code (Monaco API/Fiber) -> wait_thinking_pacing -> Network/DOM TwoPhaseEval -> diff_extractor -> trigger_next_level`。
- **两阶段防竞态与网络层拦截**：优先通过 CDP `expect_response` 截获后端评测 JSON 接口（`/evaluate`、`test_sets` 等），平滑回退至两阶段 DOM 快照比对（结合 `\d+S` 倒计时与 `_has_real_result` 校验），彻底消灭异步竞态假阳性。
- **Monaco/Ace 内存级穿透注入**：遍历当前 Page 及所有 Frames，不仅探测 `window.monaco` 与 `window.ace`，同时深层穿透 DOM 节点的 React/Vue Fiber 实例（`__reactFiber$`, `__vue__`），实现 100% 内存级 setValue 注入，杜绝退化为低效的键盘模拟。
- **CDP 标签页匹配**：优先匹配实训任务页 (`/tasks/`, `/shixuns/`) 与作业列表页 (`/shixun_homework`, `/homeworks`, `/classrooms/<id>`)，自动规避纯 `/classrooms` 班级总览页，支持 `--match` 关键词精确匹配。

