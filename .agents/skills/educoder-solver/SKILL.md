---
name: educoder-solver
description: 头歌平台 (Educoder) 全自动接管与答题专家。支持课堂大作业单步原子流与全自动巡航 (run-classroom-homework/open-task)，具备实训详情跳板页自动穿透、多 Tab 生命周期自动回收、prefer_type 智能定向解耦、60s防秒刷跨进程打卡持久化控速、React Fiber 深度穿透真实保存 (onChange/onSave/commitID/Ctrl+S) 与单题关卡闭环答题 (solve-cycle)。在用户输入 /educoder-solver、请求自动完成整门课作业或解答实训题目时使用。
---

# 头歌自动答题与实训接管专家 (Educoder Solver Skill v4.1)

本 Skill 赋能 AI Agent 直接接管并操作用户已登录的头歌（Educoder）物理浏览器，形成**“感知 -> 推演 -> 跨进程持久化控速 -> React Fiber真实保存 -> 复合流水线作答 -> 双轨评测自愈 -> 课堂大作业巡航与跳板穿透 -> 多 Tab 智能解耦与回收”**的完整全自动答题闭环。

---

## 核心工作哲学与铁律边界

1. **大脑与手眼分离**：你（AI）是大脑，负责语义理解、算法编写与自愈纠错；本地 CLI 工具（`python -m src.cli`）是手眼，负责精准执行浏览器交互。
2. **纯本地决策**：严禁调用任何外部第三方商业大模型 API，所有题目的推演、解题思路与代码编写均由你直接生成。
3. **课堂大作业官方命令链与多 Tab 智能解耦**：若检测到处于课堂实训作业列表页，一问一答型短连接 AI Agent **强烈推荐单步原子流（`list-tasks` -> `open-task` -> `solve-cycle`）**；具备实时双向 stdio 通信环境方可使用 `run-classroom-homework --interactive`；`open-task` 已原生内置跳板详情页自动穿透、旧关卡 Tab 自动回收与开题打卡持久化；CLI 命令底层按职责解耦（列表匹配 classroom，解题匹配 shixun），严禁私自手写未经封装的临时 Python 脚本操作 Tab。
4. **防秒刷控速与跨进程打卡持久化 (Anti-Cheat Pacing & Persistence)**：单关作答必须执行智能思考控速（默认 `--min-duration 60` 配合 `5~20s` 离散浮动）。开题打卡时间戳原子持久化至 `.cache/pacing_state.json`，解决短连接模式下时间戳内存丢失导致的重复 60s+ 盲等，等待期间注入微滚动活跃心跳，严禁秒刷触发教师端作弊审查。
5. **React Fiber 真实保存与 Git 提交闭环**：代码注入必须穿透 React Fiber 调用 `ed.onChange` 与 `ed.onSave` 并提取后端 `commitID`，配合 `Ctrl+S` 键盘双重兜底，确保回执 `saved == true` 且云端代码真实同步后方可触发评测，彻底根除评测沙箱拉取到空代码或初始模板的致命缺陷。
6. **低熵输出与信息提纯**：题干中的 `<table>` 必须转为 Markdown 表格，图片剔除 base64 噪音，评测回执收敛为高密度 `diff_hint`，全面保护 AI 思考题目的心智带宽。
7. **两阶段防竞态与安全熔断**：双轨评测监听（网络层优先 + DOM 兜底校验 `\d+S` 倒计时与 `_has_real_result`）；连续 3 次相同报错强制熔断报警。

---

## 执行标准作业流程 (SOP)

当用户输入 `/educoder-solver [用户指令]`（例如：`/educoder-solver 帮我自动完成当前头歌实验`、`/educoder-solver 把这门课的作业全跑完` 或 `/educoder-solver 做这道题`）时，按以下状态机执行：

```mermaid
flowchart TD
    Start["收到指令 (/educoder-solver)"] --> Check["步骤 1: 探活端口与标签页 (check-browser --json)"]
    Check -->|未就绪/离线| GuideUser["输出指导: 提示用户运行启动脚本并登录"]
    GuideUser --> EndWait["等待用户反馈已就绪"]
    Check -->|就绪| Detect{"判定当前页面形态"}
    
    %% 路径 A: 课堂作业列表
    Detect -->|作业列表页| BranchA{"选择作业推进模式"}
    BranchA -->|推荐: 短连接 Agent 单步原子流| ScanList["步骤 A1: 扫描大题列表<br>list-tasks --json"]
    ScanList --> OpenTask["步骤 A2: 开启并激活大题 (open-task --json)<br>自动穿透跳板页直达 IDE & 开题打卡持久化"]
    OpenTask --> Dump
    
    BranchA -->|可选: 长连接双向 stdio 协程流| Cruise["步骤 A3: 交互式巡航 (30s 超时保护)<br>run-classroom-homework --interactive --json"]
    Cruise --> CruiseReport["解析巡航报表 -> 向用户汇总汇报"]
    CruiseReport --> Done["交付完成"]

    %% 路径 B: 单题目关卡
    Detect -->|单题关卡页| Dump["步骤 2: 提取当前题目结构 (dump-question --json)<br>代码题自动补全开题打卡"]
    Dump --> Branch{"步骤 3: 识别题型与智能作答"}
    
    Branch -->|choice / judgment| SolveChoice["推演算题 -> 提交选项 (submit-choice)"]
    Branch -->|blank| SolveBlank["推演槽位 -> 注入填空 (submit-blank)"]
    Branch -->|practical| SolveCode["编写核心算法 -> 复合流水线 (solve-cycle --min-duration 60)<br>跨进程精确差额控速 + React Fiber 真实保存 + 双轨评测"]
    
    SolveCode --> EvalCheck{"评测是否通过?"}
    EvalCheck -->|100% 通过| DoneReport["步骤 4: 汇报成果 / 自动清理打卡记录 / 流转下一关"]
    DoneReport --> LoopNext{"大题所有关卡是否通关?"}
    LoopNext -->|已通关全部关卡| BackList["切回列表页推进下一题 (list-tasks)"]
    BackList --> Done
    LoopNext -->|仍有下一关| Dump
    
    EvalCheck -->|未通过 且 < 3次| SelfHeal["自愈纠错: 基于 diff_hint 针对性修正代码"]
    SelfHeal --> SolveCode
    EvalCheck -->|连续 3 次相同报错| CircuitBreak["触发安全熔断: 汇报卡点并求助人类"]
    SolveChoice --> Done
    SolveBlank --> Done
```

---

### 步骤 1：前置探活与页面形态研判

在当前项目虚拟环境下执行浏览器探活命令（务必附带 `--json`）：

```powershell
.\.venv\Scripts\python -m src.cli check-browser --json
```

- **分支 1.1 (离线 / 无头歌页面)**：
  如果返回 `"cdp_available": false` 或 `"has_educoder_page": false`，**切勿盲目重复调用命令**，立即向用户输出清晰友好的三步指引：
  > 💡 **请先启动调试浏览器并登录关卡**：
  > 1. 打开终端运行脚本：`.\scripts\launch_browser.ps1`（或双击运行 `scripts\launch_browser.bat`）；
  > 2. 在弹出的浏览器窗口中登录您的头歌账号，并进入待作答的课堂作业列表或实验关卡页面；
  > 3. 准备好后请回复我，我将立即为您继续自动作答。

- **分支 1.2 (在线就绪 - 课堂作业列表页)**：
  如果页面标题或 URL 包含 `classrooms`, `homeworks`, `shixuns`，且包含多个实训大题卡片，**直接跳转至【场景 A：课堂作业推进工作流】**。

- **分支 1.3 (在线就绪 - 单题关卡页)**：
  如果已处于具体题目的作答页面，推进到步骤 2。

---

### 场景 A：课堂作业推进工作流 (Classroom Homework Workflow)

#### 模式 A1：短连接 Agent 单步原子流 (强烈推荐，一问一答型 AI 首选)
现代 Agent 环境的 CLI 执行工具（如 `run_command`）属于短周期阻塞调用，无法在单次执行中途双向交互。因此**单步原子流是百分之百稳健、无死锁的黄金解法**：

1. **只读扫描大题列表**：
   ```powershell
   .\.venv\Scripts\python -m src.cli list-tasks --json
   # 若打开了多个标签页，可加 --match 精确匹配：
   .\.venv\Scripts\python -m src.cli list-tasks --match homework --json
   ```
   返回干净的 JSON 数据，展示大题总数、待完成列表与按钮可用状态。

2. **单步开启指定大题 (含跳板详情页自动穿透与开题打卡持久化)**：
   ```powershell
   # 默认自动开启第 1 个未完成的大题并激活新 Tab
   .\.venv\Scripts\python -m src.cli open-task --json
   # 或显式指定大题序号 (0-indexed)：
   .\.venv\Scripts\python -m src.cli open-task --index 1 --json
   ```
   - **跳板详情页自动穿透 (`penetrate_detail_springboard`)**：头歌部分大题在点击后会进入 `/detail?tabs=` 介绍页，底层会自动探测并点击“继续挑战”/“开始实训”直达编程 IDE 关卡，并安全关闭中间跳板页，**无需 AI 进行二次开题识别**。
   - **多 Tab 智能生命周期回收 (`cleanup_old_task_pages`)**：开启新关卡后，底层会自动扫描当前上下文，安全回收除当前活动页外的所有旧实训 Tab，保留作业列表页，彻底杜绝标签页堆积与内存泄露。
   - **开题打卡跨进程持久化 (`.cache/pacing_state.json`)**：捕获新关卡后，自动记录当前关卡开题时间戳至本地持久化缓存，供后续 `solve-cycle` 跨进程读取并精确扣减思考已耗时。
   - **首关预感知与遮罩扫除**：将其激活置顶并自动清理阻塞遮罩，返回首关概要及题型预览。

3. **关卡内闭环推进**：
   此时浏览器焦点已切换到该大题关卡，直接调用单关流程：
   - 提取题目：`.\.venv\Scripts\python -m src.cli dump-question --json`
   - 推演算法并通过复合流水线注入作答：
     ```powershell
     # 复合答题并自动下一关，可选 --close-on-complete (通关后自动安全关闭当前关卡 Tab)
     .\.venv\Scripts\python -m src.cli solve-cycle --code "<你的核心代码>" --auto-next --min-duration 60 --close-on-complete --json
     ```
   - 关卡评测全绿并通过 `--auto-next` 进入下一关；重复此步直至整道大题所有关卡通关。

4. **推进下一道大题**：
   一道大题通关后，再次执行 `list-tasks --json` 检查进度（底层通过 `prefer_type="classroom"` 自动精准命中作业列表页），继续 `open-task --json` 进入下一道大题，直至全课程作业完成。

#### 模式 A2：长连接双向 stdio 协程流 (`run-classroom-homework --interactive`)
仅在你的环境支持长连接后台守护进程并具备持续向 stdin 写入 JSON Lines 通道时使用：
- **启动指令**：
  ```powershell
  .\.venv\Scripts\python -m src.cli run-classroom-homework --interactive --min-duration 60 --json
  ```
- **握手协议规范**：
  1. CLI 在开题后向 `stdout` 输出 JSON 事件：
     `{"event": "question_detected", "task_title": "...", "level_index": 1, "question_type": "practical", "question_data": {...}}`
  2. 外部控制器从 `stdin` 回复动作指令（内置 30s 超时看门狗保护，超时安全退出）：
     `{"action": "solve", "code": "SELECT 1;", "target_only": true}` 或 `{"action": "skip"}`
  3. CLI 触发评测并向 `stdout` 回传评测结果：
     `{"event": "eval_result", "passed": true, "diff_hint": "通过"}`
- **演练模式 (仅扫描列题不点击)**：
  ```powershell
  .\.venv\Scripts\python -m src.cli run-classroom-homework --dry-run --json
  ```

---

### 步骤 2：题目感知与 Markdown 表格提取

在具体关卡页面执行题目提纯命令：

```powershell
.\.venv\Scripts\python -m src.cli dump-question --json
```

系统将返回标准化的 `QuestionData` JSON：
- `type`: 题目类型（`choice`, `multiple_choice`, `judgment`, `blank`, `practical`）
- `description`: 题干（**已自动将 HTML `<table>` 转换为标准 Markdown 表格，图片已剔除 base64 转为 `[附图说明: xxx]`**）
- `practical_details`: 实训专属数据（任务要求、输入输出样例、`prefix_code` / `target_code` / `suffix_code` 靶心区域、`is_blank_slate` 是否为无模板白纸题）
- **空白开卷题显式感知 (Blank Slate)**：若 `practical_details.is_blank_slate == true`，表示关卡未提供初始代码骨架，需要 AI 从头全量编写完整代码。
- **SPA 加载态防抖自愈**：关卡提取入口内置 3.5s 防抖等待，等待异步加载指示器（“努力请求数据中”或 `.ldsRing`、`.ant-spin-spinning`）消失且容器挂载完成，彻底杜绝关卡切换瞬间误判为 unknown。
- **智能开题补打卡**：当识别到实训代码题且尚未打卡时，CLI 自动将当前关卡开题时间写入 `.cache/pacing_state.json`，确保无论从哪个入口进入关卡，控速器都有精确时间戳起点。

---

### 步骤 3：根据题型推演并下发动作

#### 场景 3.1：客观选择题与判断题 (`choice` / `multiple_choice` / `judgment`)
1. **AI 独立推理**：仔细阅读题干与选项文本，推导正确答案（如单选 `A`，多选 `A,C`，判断 `正确`）。
2. **下发点击指令**：
   ```powershell
   .\.venv\Scripts\python -m src.cli submit-choice --options A,C --json
   ```
   *(注：内置防反选保护，已勾选的选项自动跳过，绝不发生误取消)*

#### 场景 3.2：文本填空题 (`blank`)
1. **分析槽位**：结合空位前后文（`prefix_text`, `suffix_text`）和提示（`hint`），推导各槽位内容。
2. **下发填空指令**：
   ```powershell
   .\.venv\Scripts\python -m src.cli submit-blank --answers '["答案一", "答案二"]' --json
   ```

#### 场景 3.3：编程实训题 (`practical`)
1. **解析核心要求**：
   - 阅读 `task_description` 与题干中的 Markdown 表格（如数据表字段规范）；
   - 查看 `sample_io` 样例；
   - 审阅 `prefix_code` 与 `suffix_code`，确认待编写的靶心算法区域（`Begin - End` 之间）。
2. **生成靶心代码**：
   - 编写高鲁棒性、处理边界情况的核心实现，保持正确的缩进；
   - **绝不要**将外围 `prefix_code` 或 `suffix_code` 重复写在靶心代码中。
3. **极速闭环注入与控速评测 (强烈推荐复合流水线)**：
   ```powershell
   .\.venv\Scripts\python -m src.cli solve-cycle --code "<你的核心代码>" --min-duration 60 --json
   ```
   *(注：单次调用自动完成【清理遮罩 -> Monaco/Fiber 内存穿透注入 -> React Fiber 显式调用 onChange 与 onSave 并提取 commitID / Ctrl+S 兜底保存 -> 读取持久化开题打卡精确扣减差额与保鲜心跳 -> CDP网络层拦截优先双轨评测 -> 高密度Diff提取】)*
   - **回执契约检查**：回执中的 `injection` 对象包含 `"saved": true` 与 `"commit_id": "commit_..."`，确认代码真正提交至云端 Git 仓库。
4. **处理评测反馈（自愈回路）**：
   - 若 `passed: true`：评测全绿通过！系统自动清理本关打卡缓存并向用户通报通关。
   - 若 `passed: false`：查看回执中的 `diff_hint`、`expected`、`actual` 与 `error_msg`。
     - 调整算法并重新执行 `solve-cycle --min-duration 60 --json`；
     - **熔断红线**：若同一道题目连续 3 次返回完全一样的报错（`circuit_broken == true`），**必须立即停止重复评测**，向用户汇报当前卡点，请求人类协同介入。

---

### 步骤 4：关卡流转与总结

1. 一关顺利完成后，向用户汇报作答总结（题目、推导答案、评测通过率、耗时）。
2. 若用户要求连续答题，可在流水线中开启 `--auto-next`：
   ```powershell
   .\.venv\Scripts\python -m src.cli solve-cycle --code "<代码>" --auto-next --min-duration 60 --json
   ```
   自动点击平台上的“下一关”按钮进入后续关卡。

---

## 常见问题与避坑指南 (Troubleshooting)

| 典型场景与报错 | 根本原因 | 官方推荐处理手法 |
| :--- | :--- | :--- |
| **评测结果显示实际输出为空 / 初始模板代码未生效** | 头歌 React SPA 状态未同步，未向平台 Git 提交代码 | v4.0 已实现 React Fiber 深度穿透：注入时显式调用 `ed.onChange` 与 `ed.onSave` 并提取 `commit_id`，配合 `Ctrl+S` 双重兜底，确保代码真正持久化至后端 Git 仓库后再评测。 |
| **短连接 CLI 模式下每道题重复盲等 60s+ 甚至 75s+** | 短连接模式下进程退出导致开题打卡内存丢失，误以为刚刚开题 | v4.0 引入 `.cache/pacing_state.json` 跨进程打卡持久化，`open-task` 与 `dump-question` 自动打卡，`solve-cycle` 精确计算并扣减思考已耗时，超时则 0 秒直出。 |
| **`open-task` 停留在 `/detail?tabs=` 详情页无法直接做题** | 部分大题包含前置实训介绍跳板页，未直接进入 IDE 编程关卡 | v4.0 内置 `penetrate_detail_springboard` 自动穿透机制，检测到跳板页自动点击“开始实训/继续挑战”直达 IDE，并安全关闭中间页，无需 Agent 二次开题。 |
| **编辑器无法识别或提示 `window.Monaco` 报错** | 部分关卡打包配置使用首字母大写 `window.Monaco` 或类名 `.my-monaco-editor` | v4.0 已全面兼容 `window.monaco || window.Monaco` 及容器类名 `.monaco-editor, .my-monaco-editor`，支持跨 Frames 与 Fiber 穿透识别。 |
| **执行命令后进程假死/挂起** | 调用了 `run-classroom-homework --interactive`，但当前 Agent 的工具是单次短连接阻塞调用，无法在运行时输入 stdin | **切勿使用交互式巡航**。改用推荐的**单步原子流（模式 A1）**：`list-tasks` -> `open-task` -> `dump-question` -> `solve-cycle`。系统已内置 30s 看门狗超时保护，超时会自动释放。 |
| **扫描结果为 0 道大题 / 静默空跑** | 浏览器停留在 `/classrooms` 班级总览页而非具体的作业列表页，或者打开了多个不相关标签页 | 执行命令时显式加上 `--match` 参数精确匹配目标 URL，例如：`list-tasks --match homework --json` 或让用户点进课程作业列表。 |
| **实训题评测报错提示靶心代码为空** | 关卡中缺少靶心代码标记，或未传入解题算法 | 系统已加入靶心空代码拦截保护，不再拿空白模板盲目评测。请先 `dump-question` 观察题干与靶心区域，再通过 `solve-cycle --code "<代码>"` 正确下发解题逻辑。 |
| **不知道如何连续刷完整门课作业** | 以为必须手写临时脚本切换 Tab | **严禁手写任何临时脚本**！官方原生支持单步推进：每做完一个大题的全部关卡，直接再次执行 `list-tasks --json` 检查进度并 `open-task --json` 进入下一道大题。 |

---

## 进阶参考手册

若需要查阅底层 CLI 的参数签名、JSON 契约格式、控速算法或 Monaco 注入细节，可随时查阅项目内的完整操作手册：
- [docs/AI_MANUAL.md](file:///e:/项目/tou%20ge/docs/AI_MANUAL.md)
- [references/ai_manual.md](references/ai_manual.md)
