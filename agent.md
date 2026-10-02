# AGENTS.md - 头歌自动答题系统规范与行为准则

## 1. 项目定位与技术栈 (Project & Stack)
- **项目目标**：通过本地 CDP (Chrome DevTools Protocol) 挂载物理浏览器接管头歌平台，由本地 AI 代理直接闭环进行“感知-推理-答题-自愈”，严禁依赖外部付费 API。
- **技术栈**：Python 3.12+ / Playwright (CDP Remote Debugging) / BeautifulSoup4 / Rich / Argparse / Pytest
- **依赖管理**：推荐使用专用 venv (`.venv`) 与 `pip`。

## 2. 核心指令 (Core Commands)
- **环境初始化**：`python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt`
- **Playwright 安装**：`playwright install chromium`（仅备用，主流程挂载本机 9222 端口无需下载大浏览器）
- **浏览器端口探针**：`python -m src.cli check-browser`
- **页面检测与题目提取**：`python -m src.cli dump-question`
- **复合闭环流水线 (推荐实训题首选)**：`python -m src.cli solve-cycle --code "<target_code>" [--file <path>] [--full] [--auto-next] --json`
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
- **实训优先复合流水线**：实训题作答优先使用 `solve-cycle` 单次会话流水线，将“弹窗清理-Monaco注入-两阶段防竞态评测-Diff提纯-流转”收敛在单次 CDP 进程内，杜绝多次进程冷启动开销。
- **低熵输出与信息提纯**：对评测结果和报错必须经过提纯器（如 `TestcaseDiffExtractor` 与 `clean_text_content`）过滤 ANSI 转义码与 DOM 噪音，仅向 AI 呈现 `expected`、`actual`、`diff_hint` 与精炼异常。
- **弹窗与遮罩自动清理**：在执行代码注入或评测交互前，必须调用 `dismiss_blocking_overlays` 自动清除过关庆祝弹窗及阻断鼠标事件的残留遮罩（pointer-events: none / display: none）。
- **两阶段防竞态评测监听**：触发评测必须执行两阶段监听——第 1 阶段（0.5s~0.8s 观察期等待 loading 启动或弹窗出现）；第 2 阶段（轮询等待 loading 消失，并通过 DOM 结果快照比对验证内容已发生实质变化，防读历史旧缓存）。
- **只读最小侵入**：默认通过 DOM 查询提取题目，除非必要不注入破坏性脚本；执行代码写入前必须自动进行本地持久化快照备份（`.cache/backups/`）。
- **真实拟真延迟**：选择题点击与代码提交间必须加入随机微延迟（0.5s - 1.5s），禁止机器级并发连点触发防刷风控。
- **结构化 JSON 输出**：CLI 工具对外输出必须保持格式整洁的 JSON，便于 AI Agent 无损解析并推演。
- **测试通过再交付**：代码修改后必须执行全套测试（`pytest`），全绿通过方可交付，禁止提交带有未捕获异常的代码。

### Ask first (变更前确认)
- **高危破坏性操作**：需要清空编辑器已有代码、强制重置关卡或覆盖用户本地环境配置时，必须先征得用户确认。
- **引入庞大依赖**：引入除轻量网络/解析/CLI 之外的新重型库（如 Selenium、庞大视觉框架）前，需说明必要性并确认。

### Never do (绝对红线)
- **严禁向大模型吐出未经清洗的大段 DOM/HTML 杂音**：严禁将原始网页树、内联样式、第三方脚本或未解析的 DOM 源码塞入上下文，防止污染 AI 心智带宽。
- **严禁引入第三方商业大模型 API**：禁止任何添加外部商用 API Key（如 OpenAI / Claude API）的要求，决策大脑由本地 AI 担当。
- **严禁硬编码用户凭证**：不得在代码中存储用户名、密码或 Token，会话完全复用物理浏览器已有 Cookie。
- **严禁盲目死循环评测**：若连续 3 次评测报错未发生变化，必须停止触发“评测”按钮并向用户发出告警，严禁无限消耗平台评测配额。

## 4. 关键代码范式 (Code Patterns)
- **单会话复合答题流水线 (Solve Cycle)**：通过 `run_solve_cycle()` 在同一个页面生命周期内串联 `ModalSweeper -> inject_code -> trigger_and_wait_eval -> diff_extractor -> trigger_next_level`，单循环耗时控制在 5~8s 内。
- **两阶段防竞态监听**：必须比对评测前 DOM 快照（`pre_snapshot`）与评测后容器，确保捕获的是本次提交产生的最新异步回执，避免因网络延迟提前误判。
- **Monaco/Ace 编辑器注入**：优先通过 `page.evaluate()` 触发编辑器内部 API（如 `monaco.editor.getModels()[0].setValue(val)`），若失败则回退至焦点全选覆盖，严禁直接 innerHTML 破坏 DOM 挂载。
- **CDP 标签页匹配**：遍历 `browser.contexts[0].pages`，通过 URL 包含 `educoder.net` 匹配目标 Tab，严禁随意关闭用户其它正在浏览的标签页。
