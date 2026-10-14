# AGENTS.md - 头歌自动答题系统规范与行为准则

## 1. 项目定位与技术栈 (Project & Stack)
- **项目目标**：通过本地 CDP (Chrome DevTools Protocol) 挂载物理浏览器接管头歌平台，由本地 AI 代理直接闭环进行“感知-推理-控速-答题-自愈-巡航”，严禁依赖外部付费 API。
- **技术栈**：Python 3.12+ / Playwright (CDP Remote Debugging) / BeautifulSoup4 / Rich / Argparse / Pytest
- **架构版本**：v4.1.0 (支持标签页智能解耦 prefer_type、隐形字符/行尾空格高敏 Diff、SPA 加载态防抖自愈 wait_for_spa_loading、空白题显式感知 is_blank_slate、多 Tab 自动回收 cleanup_old_task_pages、Pacing 跨进程持久化思考控速防秒刷、Classroom Orchestrator 跳板自动穿透、React SPA 深度 Fiber 真实保存、全局 Monaco 大小写兼容、题干表格 Markdown 结构化、CDP 网络层评测拦截)
- **依赖管理**：推荐使用专用 venv (`.venv`) 与 `pip`。

## 2. 核心指令 (Core Commands)
- **环境初始化**：`python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt`
- **Playwright 安装**：`playwright install chromium`（仅备用，主流程挂载本机 9222 端口无需下载大浏览器）
- **浏览器端口探针**：`python -m src.cli check-browser`
- **页面检测与题目提取**：`python -m src.cli dump-question` (支持 SPA 加载防抖自愈与 `is_blank_slate` 感知)
- **课堂大作业推进 (双模式支持)**：
  - **模式 1 (AI Agent 单步原子流，短连接 Agent 强烈首选)**：
    - 列表只读扫描：`python -m src.cli list-tasks [--match <keyword>] --json` (自动 prefer_type=classroom)
    - 单步开启大题 (含跳板穿透、旧Tab回收与持久打卡)：`python -m src.cli open-task [--index <N>] [--match <keyword>] --json`
    - 关卡闭环作答 (含跨进程控速、真实保存与可选通关关Tab)：`python -m src.cli solve-cycle --code "<target_code>" [--file <path>] [--close-on-complete] --auto-next [--min-duration 60] --json`
  - **模式 2 (长连接双向协程流，带 30s 超时保护)**：
    - 交互式全自动巡航：`python -m src.cli run-classroom-homework [--max-tasks 10] [--min-duration 60] [--dry-run] [--interactive] [--match <keyword>] --json`
- **单关复合闭环流水线 (实训单题首选)**：`python -m src.cli solve-cycle --code "<target_code>" [--file <path>] [--full] [--close-on-complete] [--auto-next] [--min-duration 60] --json`
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
- **标签页场景智能定向匹配准则**：在调度浏览器页面时必须遵循职责解耦：列表扫描与大题开启优先命中作业列表页 (`prefer_type='classroom'`)，关卡提取与代码评测优先命中实训关卡页 (`prefer_type='shixun'`)，杜绝上一题做完后因仍处于实训 Tab 导致切回列表失败。
- **课堂大作业官方命令链准则**：在面对整门课作业列表页面时，**必须使用官方命令链推进**：一问一答型短连接 AI Agent 优先使用单步原子流（`list-tasks` 扫描列表 -> `open-task` 激活新 Tab -> `dump-question` 感知题目 -> `solve-cycle` 闭环做题）；具备实时双向 stdio 管道的外部进程方可使用 `run-classroom-homework --interactive`。
- **React Fiber 真实保存与 Git 提交闭环**：代码注入必须穿透 React Fiber 调用 `ed.onChange` 与 `ed.onSave` 并提取后端 `commitID`，配合 `Ctrl+S` 键盘双重兜底，确保回执 `saved == true` 且云端代码真实同步后方可触发评测，彻底根除评测沙箱拉取到空代码或初始模板的致命缺陷。
- **防秒刷控速与跨进程打卡持久化 (Anti-Cheat Pacing & Persistence)**：严禁单关卡毫秒级秒刷触发教师端审查与平台风控！单关提交必须经过智能控速（默认 `--min-duration 60` 配合 `5~20s` 拟真离散抖动）。开题打卡时间戳必须原子持久化至 `.cache/pacing_state.json`，在短连接 CLI 模式下精准扣除已耗时，通关自动清理缓存记录；等待期间注入微滚动保活心跳（每 15s），本地快速自测或明确极速要求方可传 `0`。
- **隐形字符与行尾空格高敏识别**：比对评测输出时，若文本内容一致但存在空白/换行字符不匹配，必须生成 repr 级别的行尾空格精准差异提示，严禁误报为“输出与预期一致”误导决策。
- **跳板详情页自动穿透与旧 Tab 回收**：开启大题命中 `/detail?tabs=` 跳板介绍页时，必须通过 `penetrate_detail_springboard` 自动点击“开始实训/继续挑战”直接穿透至真正 IDE 关卡并安全关闭跳板页与此前已通关的旧关卡 Tab，防止 Chrome 内存无限膨胀。
- **SPA 加载态防抖与空白题感知**：关卡感知时必须调用 `wait_for_spa_loading` 过滤“努力请求数据中..”等瞬态抖动；若编辑器无初始模板，显式输出 `is_blank_slate: true` 指引 AI 全量注入。
- **实训优先复合流水线**：实训题作答优先使用 `solve-cycle` 单次会话流水线，将“弹窗清理-Monaco穿透注入与保存-控速等待-网络层/DOM双轨评测-Diff提纯-流转”收敛在单次 CDP 进程内，杜绝多次进程冷启动开销。
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
- **严禁仅修改 Monaco Model 内存即盲目触发评测**：严禁在未确认 React 组件状态更新与云端代码真实保存（`saved: true`）的情况下点击评测，防止向评测沙箱提交空文件或旧模板代码。
- **严禁代码与文档 Skill 脱节交付**：严禁在更新了核心 CLI 接口或工作流规范后，遗漏对 `docs/AI_MANUAL.md`、`SKILL.md`（含附录 `references/ai_manual.md`）及宿主全局 Skill 库的同步更新，防止后续 AI Agent 读取过时契约导致交互死锁或空跑。
- **严禁向大模型吐出未经清洗的大段 DOM/HTML 杂音**：严禁将原始网页树、内联样式、base64 图片数据、第三方脚本或未解析的 DOM 源码塞入上下文，防止污染 AI 心智带宽。
- **严禁直接秒刷导致被教师端审计**：禁止在生产环境关卡绕过思考控速机制以低于 5 秒的时长连刷通关。
- **严禁私自编写临时 Python 脚本切换 Tab 或操作题目**：严禁在项目根目录或 `.cache/` 临时生成 `.py` 脚本来执行浏览器操作，所有列表扫描、大题开启、代码注入、关卡评测必须全部使用官方 CLI 子命令。
- **严禁引入第三方商业大模型 API**：禁止任何添加外部商用 API Key（如 OpenAI / Claude API）的要求，决策大脑由本地 AI 担当。
- **严禁硬编码用户凭证**：不得在代码中存储用户名、密码或 Token，会话完全复用物理浏览器已有 Cookie。
- **严禁将过程性意见与内部建议文档纳入版本库**：禁止将各类内部优化建议（如 `*建议*.txt`、`jianyi*.txt`、`youhua*.txt`）添加至 Git 跟踪并提交，所有内部规划与反馈草稿必须纳入 `.gitignore` 彻底忽略。
- **严禁盲目死循环评测**：若连续 3 次评测报错未发生变化，必须停止触发“评测”按钮并向用户发出告警，严禁无限消耗平台评测配额。

## 4. 关键代码范式 (Code Patterns)
- **单步大题推进、跳板穿透与旧 Tab 回收 (Atomic Step, Springboard & Lifecycle)**：通过 `list_classroom_tasks(page)` 优先命中列表 (`prefer_type='classroom'`) -> `open_classroom_task(page, index)` 点击并捕获切换新 Tab -> 自动调用 `penetrate_detail_springboard()` 穿透 `/detail` 跳板页直达关卡 IDE -> 自动执行 `cleanup_old_task_pages()` 安全关闭此前旧关卡 Tab -> 自动执行开题打卡持久化 -> 关卡内调用 `run_solve_cycle()` 循环推进。
- **标签页场景智能定向解耦 (Smart Tab Resolution Pattern)**：在 `BrowserSession.get_target_page()` 中支持 `prefer_type='classroom' | 'shixun' | 'any'`，列表类命令与关卡类命令定向分流，彻底杜绝多 Tab 状态下的错误抢占。
- **隐形字符与行尾空格高敏 Diff (Whitespace-Sensitive Diff Pattern)**：在 `diff_extractor` 中若 `expected.strip() == actual.strip()` 但 `expected != actual`，生成 repr 级行尾空格不匹配高亮提示，多测试集优先报告具体空白差异。
- **SPA 加载态防抖自愈 (SPA Loading Debounce Pattern)**：在 `extract_question()` 入口处通过 `wait_for_spa_loading()` 自动平滑等待“努力请求数据中..”等瞬态遮罩消失，杜绝切题竞态导致未知题型报错。
- **空白开卷题显式感知 (Blank Slate Perception Pattern)**：当编辑器已挂载但代码为空时，设置 `is_blank_slate: true`，赋能 AI 自信全量生成。
- **智能打卡跨进程持久化 (Pacing Persistence Pattern)**：在 `open_classroom_task` 与 `cmd_dump_question` 处自动调用 `pacing_controller.start_task(url)` 原子写入 `.cache/pacing_state.json`；`run_solve_cycle` 读取持久化缓存精确补足差额，评测通过后调用 `clear_task()` 清理记录。
- **React SPA Fiber 深度穿透与真实保存 (Fiber Save Pattern)**：DOM 遍历探查 `__reactFiber$` -> 调用 `ed.onChange(val)` 通知 State -> 调用 `ed.onSave(1)` 触发 Git Commit 提取 `commitID` -> 未保存时自动派发 `Control+S` 快捷键兜底保存，回执携带 `saved` 与 `commit_id`。
- **全局 Monaco 与容器大小写兼容 (Monaco Compatibility Pattern)**：统一探测 `window.monaco || window.Monaco`，容器选择器兼容 `.monaco-editor, .my-monaco-editor`，防止打包变异导致注入失败。
- **课堂作业自动化巡航 (Classroom Cruise)**：通过 `run_classroom_cruise()` 调度 `scan_classroom_tasks -> expect_page -> penetrate_detail_springboard -> solve_cycle -> close_task_page -> reload_list`，配合 30s stdin 超时看门狗，实现无人值守自动推进。
- **单会话复合答题流水线 (Solve Cycle)**：通过 `run_solve_cycle()` 在同一个页面生命周期内串联 `ModalSweeper -> inject_code (Monaco Fiber + React onSave + Ctrl+S) -> wait_thinking_pacing (读取跨进程打卡) -> Network/DOM TwoPhaseEval -> diff_extractor -> clear_task -> trigger_next_level`。
- **两阶段防竞态与网络层拦截**：优先通过 CDP `expect_response` 截获后端评测 JSON 接口（`/evaluate`、`test_sets` 等），平滑回退至两阶段 DOM 快照比对（结合 `\d+S` 倒计时与 `_has_real_result` 校验），彻底消灭异步竞态假阳性。
