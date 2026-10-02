# 头歌自动答题系统 - 面向 AI 代理的操作手册 (AI Manual)

> **版本**：v1.0.0  
> **适用对象**：本地大型语言模型 / Agentic AI（如 Antigravity、Claude Code、Cursor 等本地执行代理）  
> **核心原则**：纯本地推理、零商业 API 依赖、真机 CDP 拟真交互、防封号防死循环

---

## 1. 代理核心定位与工作流

你（AI 代理）在此系统中担任**“认知推演大脑”**，系统提供的 Python CLI 工具（`src.cli`）充当你的**“感知眼与执行手”**。

### 1.1 标准答题闭环状态机

```mermaid
stateDiagram-v2
    [*] --> 探活检测
    探活检测 --> 提示用户启动: 端口离线或无标签页
    提示用户启动 --> 探活检测: 用户就绪
    探活检测 --> 提取题目: 9222 端口与头歌页面就绪
    
    提取题目 --> 客观题处理: type == choice/judgment
    提取题目 --> 填空题处理: type == blank
    提取题目 --> 实训编程处理: type == practical
    
    客观题处理 --> 提交选择: 推理得出选项
    提交选择 --> 关卡流转: 记录结果
    
    填空题处理 --> 注入填空: 推理得出槽位内容
    注入填空 --> 关卡流转: 记录结果
    
    实训编程处理 --> 注入代码: 提取任务与Begin-End生成核心算法
    注入代码 --> 触发评测: 监听评测回执
    触发评测 --> 关卡流转: 评测全部通过
    触发评测 --> 自愈分析: 存在测试用例未通过或编译报错
    自愈分析 --> 注入代码: 连续报错 < 3次 (调整算法)
    自愈分析 --> 熔断求助: 连续报错 == 3次且无变化 (暂停报警)
    
    关卡流转 --> [*]: 汇报成果
```

---

## 2. CLI 接口标准调用规范

所有 CLI 命令在由 AI 代理调用时，**必须且强制附带 `--json` 参数**。系统将把结构化数据输出到 `stdout`，人类可读日志输出到 `stderr`，确保你的 JSON 解析绝无污染。

运行环境：项目根目录下的 `.venv` 虚拟环境。  
Windows 推荐执行命令前缀：`.\.venv\Scripts\python -m src.cli`

---

### 2.1 浏览器与标签页探活 (`check-browser`)

用于在任何答题操作前探查本地 9222 端口及头歌页面。

```powershell
.\.venv\Scripts\python -m src.cli check-browser --json
```

#### JSON 输出契约
- **正常在线** (Exit Code 0)：
  ```json
  {
    "status": "online",
    "cdp_available": true,
    "host": "127.0.0.1",
    "port": 9222,
    "pages_count": 2,
    "has_educoder_page": true,
    "pages": [
      {
        "index": 0,
        "title": "实训项目 - 头歌教学平台",
        "url": "https://www.educoder.net/tasks/xxxx",
        "is_educoder": true
      }
    ]
  }
  ```
- **离线或端口未开** (Exit Code 1)：
  ```json
  {
    "status": "offline",
    "cdp_available": false,
    "host": "127.0.0.1",
    "port": 9222,
    "message": "CDP 远程调试端口 127.0.0.1:9222 未开启或未就绪"
  }
  ```

> **AI 动作指南**：
> 若 `cdp_available == false` 或 `has_educoder_page == false`，**切勿盲目重复调用**。立即向用户输出友好的引导提示，告知其运行 `.\scripts\launch_browser.ps1`，在弹出的窗口中登录头歌并进入题目关卡。

---

### 2.2 提取当前页面题目 (`dump-question`)

自动探测当前关卡题型，提纯题干、选项、代码模板与核心区域。

```powershell
.\.venv\Scripts\python -m src.cli dump-question --json
```

#### JSON 输出契约 (核心字段)
```json
{
  "type": "choice | multiple_choice | judgment | blank | practical | unknown",
  "title": "题目主标题",
  "description": "题目详细说明/背景（Markdown格式）",
  "options": [
    {
      "id": "A",
      "text": "选项文本",
      "selected": false,
      "locator_index": 0
    }
  ],
  "blanks": [
    {
      "index": 0,
      "hint": "提示信息/placeholder",
      "prefix_text": "空位前置上下文",
      "suffix_text": "空位后置上下文",
      "current_value": ""
    }
  ],
  "practical_details": {
    "task_description": "实训关卡通关要求",
    "sample_io": "输入输出样例",
    "eval_instructions": "评测规则",
    "code": "当前编辑器完整代码",
    "prefix_code": "含 Begin 标记的不可变前置代码",
    "target_code": "Begin-End 之间的核心待编写算法代码",
    "suffix_code": "含 End 标记的不可变后置代码",
    "language": "python | cpp | java | sql | ...",
    "has_target_marker": true,
    "editor_type": "monaco | ace | dom"
  }
}
```

---

### 2.3 提交客观选择题/判断题 (`submit-choice`)

```powershell
# 单选或判断
.\.venv\Scripts\python -m src.cli submit-choice --options A --json
.\.venv\Scripts\python -m src.cli submit-choice --options 正确 --json

# 多选 (逗号分隔)
.\.venv\Scripts\python -m src.cli submit-choice --options A,C,D --json
```

#### 防误点反选机制 (Anti-Uncheck)
执行器内部已内置状态防反选安全校验：
- 若选项 A 当前已在页面中处于勾选状态，执行器**自动跳过点击**，防止重复点击导致取消选择。
- AI 无需担心多选题幂等性问题。

---

### 2.4 提交文本填空题 (`submit-blank`)

```powershell
.\.venv\Scripts\python -m src.cli submit-blank --answers '["答案一", "答案二"]' --json
```

执行器会自动为每个输入槽位执行 `focus` -> `fill`，并派发原生 `input`、`change`、`blur` 事件，确保 Vue / React 双向数据绑定生效并触发自动保存。

---

### 2.5 注入编程实训题代码 (`inject-code`)

```powershell
# 仅替换 Begin-End 核心算法区 (推荐且默认模式)
.\.venv\Scripts\python -m src.cli inject-code --code "    return sum(nums) / len(nums)" --json

# 全量替换整个编辑器内容
.\.venv\Scripts\python -m src.cli inject-code --code "完整代码..." --full --json

# 从本地文件读取注入
.\.venv\Scripts\python -m src.cli inject-code --file ./solution.py --json
```

#### 安全与注入规范
1. **自动备份保障**：代码覆写前，执行器已自动将原代码持久化保存在 `.cache/backups/backup_<timestamp>.<ext>`，用户历史代码绝不丢失。
2. **Monaco API 优先**：内部自动通过 `monaco.editor.getModels()[0].setValue()` 注入，杜绝直接修改 innerHTML 破坏编辑器挂载。
3. **缩进注意**：传递 `--code` 时，请保持核心算法相对于 `Begin-End` 外围骨架的标准缩进（如 4 空格）。

---

### 2.6 触发评测与自愈闭环 (`trigger-eval`)

```powershell
# 触发评测并等待评测结束 (默认超时 60 秒)
.\.venv\Scripts\python -m src.cli trigger-eval --timeout 60 --json

# 评测通过后自动点击“下一关”
.\.venv\Scripts\python -m src.cli trigger-eval --auto-next --json
```

#### JSON 输出契约
```json
{
  "status": "success",
  "passed": true,
  "pass_ratio": "3/3",
  "error_output": "",
  "stdout": "全部测试用例通过！",
  "circuit_broken": false
}
```

若存在错误：
```json
{
  "status": "failed",
  "passed": false,
  "pass_ratio": "1/3",
  "error_output": "AssertionError: Expected 42, got 0",
  "stdout": "测试用例 2 失败",
  "consecutive_identical_errors": 1,
  "circuit_broken": false
}
```

---

## 3. 核心行为红线与自愈风控体系 (Agent Guardrails)

在自动答题过程中，你必须严格遵守以下准则：

### 3.1 评测自愈循环与熔断协议 (Circuit Breaker)
当实训题评测返回 `passed == false` 时：
1. **分析错误**：仔细研读 `error_output` 与 `stdout`，对比通关要求与输入输出样例。
2. **修正代码**：重新调用 `inject-code` 写入修正后的算法。
3. **再次评测**：重新调用 `trigger-eval`。
4. **熔断阈值（强制红线）**：
   - 如果连续 **3 次** 评测返回的报错内容完全一致（`circuit_broken == true`），**严禁继续调用评测**！
   - 此时必须停止尝试，向用户汇报当前卡点、报错信息与推测原因，请求人类协同介入。

### 3.2 拟真交互防刷策略
- 所有的 CLI 动作内部均已封装 `random_delay(0.3, 0.8)` 到 `(1.5, 3.0)` 秒的拟真随机间隔。
- AI 在连续答题（如刷多道客观题）时，应在各题之间向用户输出一两句简明的题意解释与作答总结，保持自然节奏，避免瞬间连发 CLI 触发平台访问频率封控。

---

## 4. 故障排查速查表 (Troubleshooting)

| 现象 | 可能原因 | AI 对策 |
| :--- | :--- | :--- |
| `check-browser` 提示 `cdp_available: false` | 物理浏览器未开启 9222 端口 | 指导用户执行 `.\scripts\launch_browser.ps1` |
| `dump-question` 返回 `type: unknown` | 页面尚在加载或处于课程目录列表页 | 提示用户进入具体的作业/实验关卡页面 |
| `submit-choice` 未能成功勾选 | 选项标识匹配异常（如题干使用小写或特殊符号） | 从 `dump-question` 返回的 `options` 中提取确切的 `id` 或文本重新尝试 |
| `inject-code` 后评测仍为旧代码 | 编辑器未能捕获 change 事件 | 再次尝试，或采用 `--full` 全量替换模式 |
| `trigger-eval` 响应超时 | 头歌后台排队评测中或死循环 | 检查算法是否存在 `while True` 等死循环；超时后先 `dump-question` 观察状态 |
