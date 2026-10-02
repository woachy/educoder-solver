"""统一命令行调度入口 (Unified CLI Interface).

提供统一、结构化、对 AI Agent 与人类双向友好的 CLI 子命令：
1. check-browser: 探活 CDP 端口并列出物理浏览器中已打开的头歌及其他标签页
2. dump-question: 自动探测并结构化提取当前页面的题目数据 (支持 --json / --output)
3. submit-choice: 拟真提交客观选择题/多选题/判断题答案 (防反选与拟真微延迟)
4. submit-blank: 拟真填入填空题各槽位并分发双向数据绑定事件
5. inject-code: 向实训编辑器安全注入代码 (自动备份至 .cache/backups/，支持 Begin-End 靶心组装)
6. trigger-eval: 触发实训评测，轮询回执，连续报错自愈熔断保护 (支持 --auto-next)
7. submit-answer: 综合入口命令，根据 --type 路由分发
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.browser.manager import (
    BrowserSession,
    TargetPageNotFoundError,
    check_cdp_available,
)
from src.config import config
from src.executor.blank_action import submit_blank_answer
from src.executor.choice_action import submit_choice_answer
from src.executor.editor_action import inject_code
from src.executor.eval_action import EvaluationManager
from src.executor.pipeline import run_solve_cycle
from src.extractor.base import QuestionData, QuestionType
from src.extractor.detector import extract_question
from src.utils.logger import logger, print_json_result

console = Console()
err_console = Console(stderr=True)


def _handle_connection_error(e: Exception, json_mode: bool) -> None:
    """统一处理 CDP 连接异常"""
    err_data = {
        "status": "error",
        "error_type": "ConnectionError",
        "message": str(e),
        "hint": "请确保已在 9222 端口启动物理浏览器，命令: .\\scripts\\launch_browser.ps1",
    }
    if json_mode:
        print_json_result(err_data, exit_code=1)
    else:
        err_console.print(
            Panel(
                f"[bold red]CDP 连接失败[/bold red]\n\n"
                f"[yellow]{str(e)}[/yellow]\n\n"
                "[bold cyan]提示：[/bold cyan]请先在终端运行启动脚本开启物理浏览器：\n"
                "  [green].\\scripts\\launch_browser.ps1[/green]\n"
                f"或手动启动:\n"
                f"  chrome.exe --remote-debugging-port={config.browser.port} --user-data-dir=\"C:\\ChromeDebugProfile\"",
                title="错误",
                border_style="red",
            )
        )
        sys.exit(1)


def cmd_check_browser(args: argparse.Namespace) -> None:
    """检查 9222 端口并列出所有已打开的标签页"""
    host = args.host or config.browser.host
    port = args.port or config.browser.port
    json_mode = args.json or config.log.json_mode

    is_open = check_cdp_available(host, port, timeout=1.0)
    if not is_open:
        err_data = {
            "status": "offline",
            "cdp_available": False,
            "host": host,
            "port": port,
            "message": f"CDP 调试端口 {host}:{port} 未开放，物理浏览器可能未启动",
        }
        if json_mode:
            print_json_result(err_data, exit_code=1)
        else:
            err_console.print(f"[bold red]CDP 端口 {host}:{port} 不可达。[/bold red]")
            err_console.print("请先执行 [bold green].\\scripts\\launch_browser.ps1[/bold green] 启动浏览器。")
            sys.exit(1)

    try:
        with BrowserSession(host=host, port=port) as session:
            pages = session.list_pages()
            target_pages = [p for p in pages if config.browser.target_domain in p.get("url", "")]
            res_data = {
                "status": "online",
                "cdp_available": True,
                "host": host,
                "port": port,
                "total_pages": len(pages),
                "educoder_pages_count": len(target_pages),
                "pages": pages,
            }

            if json_mode:
                print_json_result(res_data)
                return

            table = Table(title=f"CDP 浏览器已连接 ({host}:{port}) - 共 {len(pages)} 个标签页")
            table.add_column("序号", justify="center", style="cyan", no_wrap=True)
            table.add_column("标签页标题", style="magenta")
            table.add_column("URL 链接", style="green")
            table.add_column("目标匹配", justify="center", style="yellow")

            for idx, p in enumerate(pages, 1):
                is_target = config.browser.target_domain in p.get("url", "")
                target_str = "[bold green]YES[/bold green]" if is_target else "[dim]NO[/dim]"
                table.add_row(str(idx), p.get("title", "")[:40], p.get("url", "")[:60], target_str)

            console.print(table)
            if target_pages:
                console.print(f"[bold green]成功匹配到 {len(target_pages)} 个头歌平台标签页！[/bold green]")
            else:
                console.print("[bold yellow]未检测到包含 'educoder.net' 的标签页，请在浏览器中打开头歌关卡。[/bold yellow]")

    except Exception as e:
        _handle_connection_error(e, json_mode)


def cmd_dump_question(args: argparse.Namespace) -> None:
    """提取当前活跃关卡的题目详情"""
    json_mode = args.json or config.log.json_mode
    force_type = None
    if getattr(args, "type", None):
        try:
            force_type = QuestionType(args.type)
        except ValueError:
            pass

    try:
        with BrowserSession() as session:
            page = session.get_target_page(config.browser.target_domain)
            q_data: QuestionData = extract_question(page, force_type=force_type)
            result_dict = q_data.to_dict()

            if args.output:
                out_path = Path(args.output).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(result_dict, f, ensure_ascii=False, indent=2)
                logger.info(f"题目数据已成功保存至 {out_path}")

            if json_mode:
                print_json_result(result_dict)
                return

            # 人类友好终端视图呈现
            panel_content = [
                f"[bold cyan]题型:[/bold cyan] {q_data.type.value}",
                f"[bold cyan]标题:[/bold cyan] {q_data.title}",
            ]
            if q_data.description:
                desc_preview = q_data.description[:300] + ("..." if len(q_data.description) > 300 else "")
                panel_content.append(f"[bold cyan]描述:[/bold cyan] {desc_preview}")

            console.print(Panel("\n".join(panel_content), title="题目基本感知", border_style="blue"))

            if q_data.options:
                opt_table = Table(title="选项列表")
                opt_table.add_column("选项", justify="center", style="cyan")
                opt_table.add_column("内容", style="white")
                opt_table.add_column("当前选中", justify="center")
                for opt in q_data.options:
                    sel_str = "[bold green]已选中[/bold green]" if opt.selected else "[dim]未选中[/dim]"
                    opt_table.add_row(opt.id, opt.text, sel_str)
                console.print(opt_table)

            if q_data.blanks:
                blank_table = Table(title="填空槽位")
                blank_table.add_column("序号", justify="center", style="cyan")
                blank_table.add_column("提示", style="yellow")
                blank_table.add_column("当前值", style="green")
                blank_table.add_column("前置上下文", style="dim")
                for b in q_data.blanks:
                    blank_table.add_row(str(b.index), b.hint, b.current_value, b.prefix_text[:30])
                console.print(blank_table)

            if q_data.practical_details:
                pd = q_data.practical_details
                prac_content = [
                    f"[bold yellow]编程语言:[/bold yellow] {pd.language or 'unknown'}",
                    f"[bold yellow]Begin-End 区域标记:[/bold yellow] {'已检测到' if pd.has_target_marker else '未检测到'}",
                    f"[bold yellow]代码总字符数:[/bold yellow] {len(pd.code)}",
                ]
                if pd.requirements:
                    prac_content.append(f"[bold yellow]通关要求:[/bold yellow] {pd.requirements[:150]}...")
                if pd.sample_io:
                    prac_content.append(f"[bold yellow]测试样例:[/bold yellow] {pd.sample_io[:150]}...")
                console.print(Panel("\n".join(prac_content), title="实训任务与靶心分析", border_style="green"))

    except Exception as e:
        _handle_connection_error(e, json_mode)


def cmd_submit_choice(args: argparse.Namespace) -> None:
    """提交客观选择题答案"""
    json_mode = args.json or config.log.json_mode
    raw_options = args.options

    # 解析选项：支持 "A,B" 或 '["A", "B"]'
    target_options: List[str] = []
    if raw_options.startswith("[") and raw_options.endswith("]"):
        try:
            target_options = json.loads(raw_options)
        except Exception:
            target_options = [o.strip() for o in raw_options.strip("[]").split(",") if o.strip()]
    else:
        target_options = [o.strip() for o in raw_options.split(",") if o.strip()]

    try:
        with BrowserSession() as session:
            page = session.get_target_page(config.browser.target_domain)
            result = submit_choice_answer(page, target_options)

            if json_mode:
                print_json_result(result)
            else:
                status_color = "green" if result.get("success") else "red"
                console.print(
                    Panel(
                        f"[{status_color}]{result.get('message')}[/{status_color}]\n"
                        f"已点击选项: [cyan]{result.get('clicked_options')}[/cyan]\n"
                        f"原本已选中: [dim]{result.get('already_selected')}[/dim]",
                        title="选择题提交结果",
                        border_style=status_color,
                    )
                )
    except Exception as e:
        _handle_connection_error(e, json_mode)


def cmd_submit_blank(args: argparse.Namespace) -> None:
    """提交文本填空题答案"""
    json_mode = args.json or config.log.json_mode
    raw_answers = args.answers

    # 解析答案：支持 '["ans1", "ans2"]' 或 'ans1,ans2'
    answers: List[str] = []
    if raw_answers.startswith("[") and raw_answers.endswith("]"):
        try:
            answers = json.loads(raw_answers)
        except Exception:
            answers = [a.strip() for a in raw_answers.strip("[]").split(",") if a.strip()]
    else:
        answers = [a.strip() for a in raw_answers.split(",") if a.strip()]

    try:
        with BrowserSession() as session:
            page = session.get_target_page(config.browser.target_domain)
            result = submit_blank_answer(page, answers)

            if json_mode:
                print_json_result(result)
            else:
                status_color = "green" if result.get("success") else "yellow"
                console.print(
                    Panel(
                        f"[{status_color}]{result.get('message')}[/{status_color}]\n"
                        f"填入数量: {result.get('filled_count')}/{result.get('total_answers')}",
                        title="填空题提交结果",
                        border_style=status_color,
                    )
                )
    except Exception as e:
        _handle_connection_error(e, json_mode)


def cmd_inject_code(args: argparse.Namespace) -> None:
    """注入实训编辑器代码"""
    json_mode = args.json or config.log.json_mode

    code_content = ""
    if args.file:
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            err = {"status": "error", "message": f"指定代码文件不存在: {file_path}"}
            if json_mode:
                print_json_result(err, exit_code=1)
            else:
                console.print(f"[bold red]错误：代码文件不存在: {file_path}[/bold red]")
                sys.exit(1)
        with open(file_path, "r", encoding="utf-8") as f:
            code_content = f.read()
    elif args.code is not None:
        code_content = args.code
    else:
        err = {"status": "error", "message": "必须提供 --code 或 --file 参数"}
        if json_mode:
            print_json_result(err, exit_code=1)
        else:
            console.print("[bold red]错误：必须提供 --code 或 --file 参数[/bold red]")
            sys.exit(1)

    target_only = not args.full

    try:
        with BrowserSession() as session:
            page = session.get_target_page(config.browser.target_domain)
            result = inject_code(page, code_content, target_only=target_only)

            if json_mode:
                print_json_result(result)
            else:
                status_color = "green" if result.get("success") else "red"
                console.print(
                    Panel(
                        f"[{status_color}]{result.get('message')}[/{status_color}]\n"
                        f"注入方式: [cyan]{result.get('method_used')}[/cyan]\n"
                        f"备份文件: [yellow]{result.get('backup_path')}[/yellow]\n"
                        f"靶心组装: {'是' if result.get('is_target_assembled') else '否 (全量注入)'}",
                        title="代码注入回执",
                        border_style=status_color,
                    )
                )
    except Exception as e:
        _handle_connection_error(e, json_mode)


def cmd_trigger_eval(args: argparse.Namespace) -> None:
    """触发评测并监听回执，具备连续报错熔断保护"""
    json_mode = args.json or config.log.json_mode
    timeout = args.timeout or 60
    auto_next = args.auto_next

    try:
        with BrowserSession() as session:
            page = session.get_target_page(config.browser.target_domain)
            eval_mgr = EvaluationManager()
            result = eval_mgr.trigger_and_wait_eval(page, timeout_seconds=timeout)

            # 若评测通过且启用了自动下一关
            if result.get("passed") and auto_next:
                logger.info("评测全部通过，正在自动进入下一关...")
                next_success = eval_mgr.trigger_next_level(page)
                result["next_level_triggered"] = next_success

            if json_mode:
                print_json_result(result)
            else:
                passed = result.get("passed", False)
                status_color = "green" if passed else ("yellow" if not result.get("circuit_broken") else "red")
                panel_text = [
                    f"[{status_color}]{result.get('message')}[/{status_color}]",
                    f"通过比例: [bold]{result.get('pass_ratio') or 'N/A'}[/bold]",
                ]
                if result.get("circuit_broken"):
                    panel_text.append("[bold red]⚠️ 连续 3 次相同报错，熔断保护已触发！[/bold red]")
                if result.get("error_output"):
                    panel_text.append(f"\n[red]报错输出摘要:[/red]\n{result.get('error_output')[:300]}")

                console.print(
                    Panel(
                        "\n".join(panel_text),
                        title="实训评测回执",
                        border_style=status_color,
                    )
                )
    except Exception as e:
        _handle_connection_error(e, json_mode)


def cmd_submit_answer(args: argparse.Namespace) -> None:
    """综合答题命令入口 (兼容 AGENTS.md 规范)"""
    q_type = args.type.lower()
    data = args.data
    json_mode = args.json or config.log.json_mode

    # 如果 data 为文件，读取文件内容
    data_content = data
    if os.path.isfile(data):
        with open(data, "r", encoding="utf-8") as f:
            data_content = f.read()

    if q_type in ("choice", "multiple_choice", "judgment"):
        # 伪造 namespace 调用 submit_choice
        fake_args = argparse.Namespace(options=data_content, json=json_mode)
        cmd_submit_choice(fake_args)
    elif q_type == "blank":
        fake_args = argparse.Namespace(answers=data_content, json=json_mode)
        cmd_submit_blank(fake_args)
    elif q_type in ("code", "practical"):
        fake_args = argparse.Namespace(code=data_content, file=None, full=args.full, json=json_mode)
        cmd_inject_code(fake_args)
    else:
        err = {"status": "error", "message": f"未知题目类型: {q_type}，支持 [choice|blank|code]"}
        if json_mode:
            print_json_result(err, exit_code=1)
        else:
            console.print(f"[bold red]错误：{err['message']}[/bold red]")
            sys.exit(1)


def cmd_solve_cycle(args: argparse.Namespace) -> None:
    """执行复合答题流水线 (清理弹窗 -> 注入代码 -> 两阶段评测 -> 提纯Diff)"""
    json_mode = args.json or config.log.json_mode

    code_content = ""
    if args.file:
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            err = {"status": "error", "message": f"指定代码文件不存在: {file_path}"}
            if json_mode:
                print_json_result(err, exit_code=1)
            else:
                console.print(f"[bold red]错误：代码文件不存在: {file_path}[/bold red]")
                sys.exit(1)
        with open(file_path, "r", encoding="utf-8") as f:
            code_content = f.read()
    elif args.code is not None:
        code_content = args.code
    else:
        err = {"status": "error", "message": "必须提供 --code 或 --file 参数"}
        if json_mode:
            print_json_result(err, exit_code=1)
        else:
            console.print("[bold red]错误：必须提供 --code 或 --file 参数[/bold red]")
            sys.exit(1)

    target_only = not args.full
    timeout = args.timeout or 60
    auto_next = args.auto_next

    try:
        with BrowserSession() as session:
            page = session.get_target_page(config.browser.target_domain)
            result = run_solve_cycle(
                page=page,
                code=code_content,
                target_only=target_only,
                auto_next=auto_next,
                timeout=timeout,
            )

            if json_mode:
                print_json_result(result)
            else:
                passed = result.get("passed", False)
                status_color = "green" if passed else ("yellow" if not result.get("circuit_broken") else "red")
                panel_text = [
                    f"[{status_color}]{result.get('message')}[/{status_color}]",
                    f"通过用例比例: [bold]{result.get('pass_ratio') or 'N/A'}[/bold]",
                    f"差异精炼提示: [bold cyan]{result.get('diff_hint') or '无'}[/bold cyan]",
                    f"流水线总耗时: [dim]{result.get('elapsed_seconds')}s[/dim]",
                ]
                if result.get("expected") or result.get("actual"):
                    panel_text.append(f"\n[green]预期输出:[/green]\n{result.get('expected')}")
                    panel_text.append(f"[yellow]实际输出:[/yellow]\n{result.get('actual')}")
                if result.get("error_msg"):
                    panel_text.append(f"\n[red]报错信息:[/red]\n{result.get('error_msg')[:300]}")
                if result.get("circuit_broken"):
                    panel_text.append("\n[bold red]⚠️ 连续 3 次相同报错，已触发熔断保护！[/bold red]")
                if result.get("next_level_triggered"):
                    panel_text.append("\n[bold green]已成功流转至下一关！[/bold green]")

                console.print(
                    Panel(
                        "\n".join(panel_text),
                        title="复合答题流水线回执 (Solve Cycle)",
                        border_style=status_color,
                    )
                )
    except Exception as e:
        _handle_connection_error(e, json_mode)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="头歌 (Educoder) 自动化交互与智能答题系统 CLI 接口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="以结构化纯 JSON 格式向 stdout 输出结果")

    subparsers = parser.add_subparsers(dest="command", help="子命令清单")

    # 1. check-browser
    p_check = subparsers.add_parser("check-browser", help="检查 CDP 端口并列出物理浏览器中已打开的标签页")
    p_check.add_argument("--host", default=None, help="CDP 主机 (默认 127.0.0.1)")
    p_check.add_argument("--port", type=int, default=None, help="CDP 端口 (默认 9222)")
    p_check.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 2. dump-question
    p_dump = subparsers.add_parser("dump-question", help="提取当前页面的题目数据与实训要求")
    p_dump.add_argument("-o", "--output", help="输出保存路径 (.json)")
    p_dump.add_argument("-t", "--type", help="强制指定题型 (choice, blank, practical 等)")
    p_dump.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 3. submit-choice
    p_choice = subparsers.add_parser("submit-choice", help="提交客观选择题/多选题/判断题")
    p_choice.add_argument("--options", required=True, help="目标选项列表，如 A 或 A,B 或 '[\"A\", \"B\"]'")
    p_choice.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 4. submit-blank
    p_blank = subparsers.add_parser("submit-blank", help="提交文本填空题答案")
    p_blank.add_argument("--answers", required=True, help="填空答案，如 '[\"ans1\", \"ans2\"]' 或 ans1,ans2")
    p_blank.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 5. inject-code
    p_code = subparsers.add_parser("inject-code", help="向实训编辑器安全注入代码")
    code_group = p_code.add_mutually_exclusive_group(required=True)
    code_group.add_argument("--code", help="待注入的代码字符串")
    code_group.add_argument("--file", help="待注入的代码文件路径")
    p_code.add_argument("--full", action="store_true", help="全量替换代码，禁用 Begin-End 靶心保护组装")
    p_code.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 6. trigger-eval
    p_eval = subparsers.add_parser("trigger-eval", help="点击评测并等待结果回执 (内置自愈熔断)")
    p_eval.add_argument("--timeout", type=int, default=60, help="最长评测等待超时 (秒，默认 60)")
    p_eval.add_argument("--auto-next", action="store_true", help="评测通过后自动点击‘下一关’")
    p_eval.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 7. submit-answer (综合命令，兼容 AGENTS.md 规范)
    p_answer = subparsers.add_parser("submit-answer", help="综合答题接口 (按题型路由)")
    p_answer.add_argument("--type", required=True, choices=["choice", "blank", "code", "practical"], help="题型")
    p_answer.add_argument("--data", required=True, help="答案数据 (文本、JSON 或文件路径)")
    p_answer.add_argument("--full", action="store_true", help="代码题是否全量覆盖")
    p_answer.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    # 8. solve-cycle (复合答题流水线)
    p_cycle = subparsers.add_parser("solve-cycle", help="复合流水线：清理弹窗 -> 注入代码 -> 两阶段评测 -> 提纯Diff反馈")
    cycle_group = p_cycle.add_mutually_exclusive_group(required=True)
    cycle_group.add_argument("--code", help="待注入的代码字符串")
    cycle_group.add_argument("--file", help="待注入的代码文件路径")
    p_cycle.add_argument("--full", action="store_true", help="全量替换代码，禁用 Begin-End 靶心保护组装")
    p_cycle.add_argument("--auto-next", action="store_true", help="评测通过后自动点击‘下一关’")
    p_cycle.add_argument("--timeout", type=int, default=60, help="最长评测等待超时 (秒，默认 60)")
    p_cycle.add_argument("--json", action="store_true", help="结构化 JSON 输出")

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """CLI 主执行入口"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 统一激活 JSON 模式
    if getattr(args, "json", False):
        config.log.json_mode = True
        logger.json_mode = True

    handlers = {
        "check-browser": cmd_check_browser,
        "dump-question": cmd_dump_question,
        "submit-choice": cmd_submit_choice,
        "submit-blank": cmd_submit_blank,
        "inject-code": cmd_inject_code,
        "trigger-eval": cmd_trigger_eval,
        "submit-answer": cmd_submit_answer,
        "solve-cycle": cmd_solve_cycle,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
