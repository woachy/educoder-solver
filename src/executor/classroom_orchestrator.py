"""课堂大作业全自动巡航编排器 (Classroom Homework Orchestrator).

负责头歌课堂/课程实训大作业列表页的全自动扫描、派发与生命周期巡航：
1. 列表页扫描感知：识别作业/实训大题卡片、提取大题名称与当前完成状态。
2. 靶向开启与 Tab 切换：过滤未完成的大题，点击“开始实训”/“继续挑战”，自动捕获并切换到新标签页。
3. 会话内多关卡自愈推进：在任务 Tab 内流转各关卡，配合控速防刷 (PacingController) 与双轨评测监听。
4. 安全关闭与列表刷新：整道大题所有关卡完成后，安全关闭任务 Tab，切回作业列表页并刷新，推进下一道大题。
5. 结构化汇总报表：输出全流程作业通关汇总指标。
"""

import time
from typing import Any, Callable, Dict, List, Optional
from playwright.sync_api import ElementHandle, Page
from rich.console import Console
from rich.table import Table

from src.executor.eval_action import EvaluationManager
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.executor.pacing import pacing_controller
from src.executor.pipeline import run_solve_cycle
from src.extractor.detector import extract_question
from src.utils.delay import random_delay
from src.utils.logger import logger


TASK_CARD_SELECTORS = [
    "div[class*='listItem']",
    ".shixun-work-item",
    ".homework-item",
    ".shixun-task-card",
    ".exercise-item",
    ".task-card",
    ".card-item",
    ".task-item",
    ".ant-list-item",
]

TASK_ACTION_BUTTON_SELECTORS = [
    ":has-text('开始学习')",
    "a:has-text('开始学习')",
    "button:has-text('开始学习')",
    "div:has-text('开始学习')",
    "a:has-text('开始实训')",
    "button:has-text('开始实训')",
    "a:has-text('继续挑战')",
    "button:has-text('继续挑战')",
    "a:has-text('去完成')",
    "button:has-text('去完成')",
    "a:has-text('进入实训')",
    "button:has-text('进入实训')",
]


def scan_classroom_tasks(page: Page) -> List[Dict[str, Any]]:
    """扫描课堂实训作业列表页，提取所有大题卡片与状态。

    Args:
        page: Playwright Page 实例

    Returns:
        List[Dict[str, Any]]: 任务卡片信息列表
    """
    tasks: List[Dict[str, Any]] = []
    if not page:
        return tasks

    # 1. 尝试匹配卡片选择器
    cards = []
    for sel in TASK_CARD_SELECTORS:
        try:
            found = page.query_selector_all(sel)
            if found:
                cards = found
                break
        except Exception:
            continue

    # 2. 如果卡片容器未匹配到，尝试直接定位所有“开始实训/继续挑战/开始学习”按钮
    if not cards:
        for btn_sel in TASK_ACTION_BUTTON_SELECTORS:
            try:
                btns = page.query_selector_all(btn_sel)
                if btns:
                    cards = btns
                    break
            except Exception:
                continue

    logger.info(f"扫描作业列表页: 发现 {len(cards)} 个大题卡片/入口")

    for idx, card in enumerate(cards):
        try:
            card_text = card.inner_text().strip() if hasattr(card, "inner_text") else ""
        except Exception:
            card_text = ""

        # 提取标题
        title = f"实训大题 #{idx + 1}"
        for title_sel in ["[class*='titleLeft']", ".task-name", ".title", ".name", "h3", "h4", "a.title"]:
            try:
                t_el = card.query_selector(title_sel)
                if t_el:
                    t_text = t_el.inner_text().strip()
                    if t_text:
                        lines = [line.strip() for line in t_text.splitlines() if line.strip() and line.strip() not in ["提交中", "补交中", "已截止", "已归档"]]
                        if lines:
                            title = lines[0]
                        else:
                            title = t_text
                        break
            except Exception:
                continue

        # 判定完成状态
        import re
        is_completed = False
        ratio_match = re.search(r'(\d+)\s*/\s*(\d+)', card_text)
        if ratio_match:
            done_cnt, total_cnt = int(ratio_match.group(1)), int(ratio_match.group(2))
            if done_cnt >= total_cnt and total_cnt > 0:
                is_completed = True
            else:
                is_completed = False
        elif any(k in card_text for k in ["已完成", "100分", "全部通过", "已通关"]):
            is_completed = True
        elif any(k in card_text for k in ["未完成", "未开始", "进行中", "去完成", "继续挑战", "开始实训", "开始学习"]):
            is_completed = False

        # 查找操作按钮
        action_btn = None
        for b_sel in TASK_ACTION_BUTTON_SELECTORS:
            try:
                btn = card.query_selector(b_sel)
                if btn and btn.is_visible():
                    action_btn = btn
                    break
            except Exception:
                continue

        # 如果 card 自身就是 button/a
        if not action_btn:
            try:
                tag_name = card.evaluate("el => el.tagName.toLowerCase()")
                if tag_name in ("a", "button") and any(
                    k in card_text for k in ["开始实训", "继续挑战", "去完成", "进入实训", "开始学习"]
                ):
                    action_btn = card
            except Exception:
                pass

        status_label = "已完成" if is_completed else ("未完成" if action_btn else "无法操作")

        tasks.append(
            {
                "index": idx,
                "title": title,
                "status": status_label,
                "is_completed": is_completed,
                "button": action_btn,
                "raw_text": card_text[:100],
            }
        )

    return tasks


def list_classroom_tasks(page: Page) -> List[Dict[str, Any]]:
    """以只读安全方式扫描并返回所有大题卡片（不含 DOM 元素句柄，可直接 JSON 序列化）。"""
    raw_tasks = scan_classroom_tasks(page)
    clean_tasks = []
    for t in raw_tasks:
        clean_tasks.append({
            "index": t.get("index", 0),
            "title": t.get("title", ""),
            "status": t.get("status", "未知"),
            "is_completed": t.get("is_completed", False),
            "can_operate": t.get("button") is not None,
            "raw_text": t.get("raw_text", ""),
        })
    return clean_tasks


def open_classroom_task(page: Page, index: Optional[int] = None) -> Dict[str, Any]:
    """单步开启指定大题（默认第 1 个未完成大题），捕获并切换到新 Tab，返回关卡感知数据。"""
    raw_tasks = scan_classroom_tasks(page)
    if not raw_tasks:
        return {"status": "error", "message": "当前页面未扫描到任何大题卡片，请确保处于课堂作业列表页"}

    target_task = None
    if index is not None:
        for t in raw_tasks:
            if t["index"] == index:
                target_task = t
                break
        if not target_task:
            return {"status": "error", "message": f"未找到索引为 #{index} 的大题卡片"}
    else:
        # 默认找到第一个未完成且有按钮的大题
        for t in raw_tasks:
            if not t["is_completed"] and t["button"] is not None:
                target_task = t
                break
        if not target_task:
            return {"status": "success", "all_completed": True, "message": "所有大题均已完成！"}

    task_title = target_task["title"]
    task_btn = target_task["button"]
    if not task_btn:
        return {"status": "error", "message": f"大题 [{task_title}] 没有可点击的操作按钮"}

    task_page = None
    context = getattr(page, "context", None)
    try:
        if context and hasattr(context, "expect_page") and callable(context.expect_page):
            try:
                with context.expect_page(timeout=10000) as page_info:
                    task_btn.click()
                task_page = page_info.value
                logger.info(f"已捕获大题新标签页: {task_page.url}")
                if hasattr(task_page, "wait_for_load_state"):
                    task_page.wait_for_load_state("domcontentloaded")
            except Exception as pe:
                logger.debug(f"expect_page 超时: {pe}")
    except Exception as e:
        logger.error(f"点击开启大题异常: {e}")

    if not task_page and context and hasattr(context, "pages") and isinstance(context.pages, list):
        if len(context.pages) > 1:
            task_page = context.pages[-1]

    if not task_page:
        task_page = page

    # 激活并聚焦新页面
    try:
        task_page.bring_to_front()
    except Exception:
        pass

    random_delay(1.0, 2.0)
    dismiss_blocking_overlays(task_page)

    # 预感知第一关
    q_data = extract_question(task_page)
    preview = {
        "title": q_data.title,
        "type": q_data.type.value if hasattr(q_data.type, "value") else str(q_data.type),
        "db_dialect": q_data.metadata.get("db_dialect"),
        "language": q_data.metadata.get("language"),
        "has_target_marker": q_data.metadata.get("has_target_marker", False),
    }

    return {
        "status": "success",
        "task_index": target_task["index"],
        "task_title": task_title,
        "task_url": getattr(task_page, "url", ""),
        "level_preview": preview,
        "message": f"已成功开启大题 [{task_title}]，进入第 1 关作答页",
    }


def _read_stdin_with_timeout(timeout: float = 30.0) -> Optional[str]:
    """安全读取 stdin，带超时与异常保护，杜绝非交互模式下的永久死锁"""
    import queue
    import sys
    import threading

    q: queue.Queue = queue.Queue()

    def _reader():
        try:
            line = sys.stdin.readline()
            q.put(line)
        except Exception:
            q.put(None)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


def run_classroom_cruise(
    page: Page,
    max_tasks: int = 10,
    min_duration: int = 60,
    auto_next: bool = True,
    solver_callback: Optional[Callable[[Page, Any], bool]] = None,
    interactive: bool = False,
    dry_run: bool = False,
    stdin_timeout: float = 30.0,
) -> Dict[str, Any]:
    """课堂大作业全自动巡航编排执行入口。

    Args:
        page: Playwright Page 实例 (主作业列表页)
        max_tasks: 最大连续执行的大题数量上限 (默认 10)
        min_duration: 每道关卡控速最小作答时长 (秒，默认 60，传 0 直出)
        auto_next: 评测通过后是否自动流转至下一关 (默认 True)
        solver_callback: 可选的自定义单关求解回调
        interactive: 是否启用基于 stdio JSON Lines 的 Agent-CLI 双向交互巡航协议
        dry_run: 演练模式，仅扫描列出待做题目，不点击提交
        stdin_timeout: 交互模式下等待 stdin 输入的超时秒数 (默认 30s)

    Returns:
        dict: 全流程作业通关汇总报表
    """
    cruise_start = time.time()
    logger.info(
        f">>> 启动课堂大作业全自动巡航编排 (最大大题数: {max_tasks}, 关卡控速: {min_duration}s, 交互模式: {interactive}, 演练: {dry_run}) <<<"
    )

    tasks = scan_classroom_tasks(page)
    total_found = len(tasks)
    pending_tasks = [t for t in tasks if not t["is_completed"] and t["button"] is not None]

    logger.info(f"巡航概况: 发现总大题 {total_found} 道，其中待完成 {len(pending_tasks)} 道")

    if dry_run:
        logger.info("[Dry Run 演练模式] 仅扫描列出任务，不实际进入关卡")
        return {
            "status": "dry_run",
            "total_tasks_found": total_found,
            "tasks_processed": 0,
            "tasks_completed": 0,
            "tasks_skipped": total_found - len(pending_tasks),
            "pending_tasks": [{"index": t["index"], "title": t["title"], "status": t["status"]} for t in pending_tasks],
            "message": f"演练扫描完成: 共发现 {total_found} 道大题，待完成 {len(pending_tasks)} 道",
        }

    task_reports: List[Dict[str, Any]] = []
    completed_count = 0
    failed_count = 0
    skipped_count = total_found - len(pending_tasks)

    for item in pending_tasks[:max_tasks]:
        task_title = item["title"]
        task_btn = item["button"]
        logger.info(f"--> 开始推进大题: {task_title}")

        task_page = None
        context = getattr(page, "context", None)

        # 1. 点击进入实训并捕获新 Tab
        try:
            if context and hasattr(context, "expect_page") and callable(context.expect_page):
                try:
                    with context.expect_page(timeout=10000) as page_info:
                        task_btn.click()
                    task_page = page_info.value
                    logger.info(f"已捕获大题新标签页: {task_page.url}")
                    if hasattr(task_page, "wait_for_load_state"):
                        task_page.wait_for_load_state("domcontentloaded")
                except Exception as pe:
                    logger.debug(f"expect_page 超时或未开启新窗口: {pe}")
        except Exception as e:
            logger.error(f"点击进入大题异常: {e}")

        # 若未成功捕获新 Tab，检查当前 pages
        if not task_page and context and hasattr(context, "pages") and isinstance(context.pages, list):
            if len(context.pages) > 1:
                task_page = context.pages[-1]

        if not task_page:
            task_page = page

        # 2. 在任务 Tab 内流转关卡
        level_count = 0
        task_success = True
        eval_mgr = EvaluationManager()

        try:
            # 单大题最多流转 20 关防止未知死循环
            for level_idx in range(1, 21):
                logger.info(f"[{task_title}] 正在检测第 {level_idx} 关...")
                random_delay(1.0, 2.0)
                dismiss_blocking_overlays(task_page)

                # 感知当前关卡
                q_data = extract_question(task_page)
                current_code = ""
                if q_data.practical_details:
                    current_code = q_data.practical_details.code or ""

                if solver_callback:
                    step_ok = solver_callback(task_page, q_data)
                elif interactive:
                    # 交互式协程协议：向 stdout 写入事件，等待 stdin 输入动作
                    import json
                    import sys

                    event_payload = {
                        "event": "question_detected",
                        "task_title": task_title,
                        "level_index": level_idx,
                        "question_type": q_data.type.value if hasattr(q_data.type, "value") else str(q_data.type),
                        "title": q_data.title,
                        "description": q_data.description,
                        "has_target_marker": q_data.metadata.get("has_target_marker", False),
                        "db_dialect": q_data.metadata.get("db_dialect", None),
                        "language": q_data.metadata.get("language", ""),
                        "editor_type": q_data.metadata.get("editor_type", "monaco"),
                        "question_data": q_data.to_dict(),
                    }
                    sys.stdout.write(json.dumps(event_payload, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

                    # 等待 Agent 输入命令 (带超时保护，杜绝死锁僵死)
                    line = _read_stdin_with_timeout(timeout=stdin_timeout)
                    if line is None:
                        logger.warning(f"[{task_title}] 等待外部 Agent 交互输入超时 ({stdin_timeout}s)，安全退出避免进程僵死")
                        timeout_event = {
                            "event": "timeout",
                            "task_title": task_title,
                            "level_index": level_idx,
                            "message": f"等待外部 Agent 交互输入超时 ({stdin_timeout}s)，未收到指令。提示：一问一答模式的 AI 请使用单步命令流（list-tasks / open-task / solve-cycle）",
                        }
                        sys.stdout.write(json.dumps(timeout_event, ensure_ascii=False) + "\n")
                        sys.stdout.flush()
                        task_success = False
                        break
                    elif not line.strip():
                        logger.warning("Agent 交互通道已关闭，退出巡航")
                        task_success = False
                        break

                    try:
                        action_cmd = json.loads(line.strip())
                    except Exception as e:
                        logger.error(f"解析 Agent 交互指令失败: {e}")
                        action_cmd = {"action": "solve", "code": current_code}

                    action_name = action_cmd.get("action", "solve")
                    if action_name == "skip":
                        logger.info(f"[{task_title}] 接收到 Agent 跳过指令")
                        break
                    elif action_name == "stop":
                        logger.info(f"[{task_title}] 接收到 Agent 终止指令")
                        task_success = False
                        break

                    solve_code = action_cmd.get("code", current_code)
                    solve_target_only = action_cmd.get("target_only", True)
                    solve_min_duration = action_cmd.get("min_duration", min_duration)

                    solve_res = run_solve_cycle(
                        page=task_page,
                        code=solve_code,
                        target_only=solve_target_only,
                        auto_next=auto_next,
                        min_duration=solve_min_duration,
                        eval_manager=eval_mgr,
                        question_data=q_data,
                    )
                    step_ok = solve_res.get("passed", False)

                    # 发送评测结果回执事件
                    eval_event = {
                        "event": "eval_result",
                        "task_title": task_title,
                        "level_index": level_idx,
                        "passed": step_ok,
                        "pass_ratio": solve_res.get("pass_ratio", ""),
                        "diff_hint": solve_res.get("diff_hint", ""),
                        "circuit_broken": solve_res.get("circuit_broken", False),
                    }
                    sys.stdout.write(json.dumps(eval_event, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

                    if solve_res.get("circuit_broken"):
                        logger.error(f"[{task_title}] 关卡连续报错触发熔断，停止推进本题")
                        task_success = False
                        break
                else:
                    # 默认使用现有复合流水线评测
                    if not current_code.strip():
                        logger.warning(
                            f"[{task_title}] 第 {level_idx} 关代码编辑器内容为空且未提供解答，跳过本题评测 (请提供 --code 或使用交互/单步模式作答)"
                        )
                        task_success = False
                        break

                    solve_res = run_solve_cycle(
                        page=task_page,
                        code=current_code,
                        target_only=True,
                        auto_next=auto_next,
                        min_duration=min_duration,
                        eval_manager=eval_mgr,
                        question_data=q_data,
                    )
                    step_ok = solve_res.get("passed", False)
                    if solve_res.get("circuit_broken"):
                        logger.error(f"[{task_title}] 关卡连续报错触发熔断，停止推进本题")
                        task_success = False
                        break

                if step_ok:
                    level_count += 1
                    logger.success(f"[{task_title}] 第 {level_idx} 关通关成功！")

                # 检查是否还有下一关
                has_next = eval_mgr.find_eval_button(task_page) is not None
                next_btn_visible = False
                for n_sel in eval_mgr.NEXT_LEVEL_SELECTORS:
                    try:
                        n_btn = task_page.query_selector(n_sel)
                        if n_btn and n_btn.is_visible():
                            next_btn_visible = True
                            break
                    except Exception:
                        continue

                # 若无下一关按钮且最后一关评测已通过，则整道大题通关
                if step_ok and not next_btn_visible:
                    logger.success(f"[{task_title}] 所有关卡已全部通关！")
                    break

        except Exception as te:
            logger.error(f"大题执行异常: {te}")
            task_success = False

        # 3. 安全关闭任务 Tab 并切回主列表页
        if task_page != page:
            try:
                task_page.close()
                logger.info(f"已安全关闭大题标签页: {task_title}")
            except Exception as ce:
                logger.debug(f"关闭任务 Tab 异常: {ce}")

        try:
            page.bring_to_front()
            page.reload()
            logger.info("已切回主作业列表页并刷新")
            random_delay(1.0, 2.0)
        except Exception:
            pass

        if task_success:
            completed_count += 1
        else:
            failed_count += 1

        task_reports.append(
            {
                "task_name": task_title,
                "initial_status": "未完成",
                "final_status": "已完成" if task_success else "未通过",
                "levels_passed": level_count,
                "success": task_success,
            }
        )

    total_elapsed = round(time.time() - cruise_start, 2)
    logger.info(
        f"<<< 课堂大作业巡航编排执行结束 (耗时: {total_elapsed}s, 完成: {completed_count}, 失败: {failed_count}, 跳过: {skipped_count}) >>>"
    )

    return {
        "status": "success",
        "total_tasks_found": total_found,
        "tasks_processed": completed_count + failed_count,
        "tasks_completed": completed_count,
        "tasks_skipped": skipped_count,
        "tasks_failed": failed_count,
        "details": task_reports,
        "elapsed_seconds": total_elapsed,
    }
