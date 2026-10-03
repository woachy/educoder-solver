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

    # 2. 如果卡片容器未匹配到，尝试直接定位所有“开始实训/继续挑战”按钮
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
        for title_sel in [".task-name", ".title", ".name", "h3", "h4", "a.title"]:
            try:
                t_el = card.query_selector(title_sel)
                if t_el:
                    t_text = t_el.inner_text().strip()
                    if t_text:
                        title = t_text
                        break
            except Exception:
                continue

        # 判定完成状态
        is_completed = False
        if any(k in card_text for k in ["已完成", "100分", "全部通过", "已通关"]):
            is_completed = True
        elif any(k in card_text for k in ["未完成", "未开始", "进行中", "去完成", "继续挑战", "开始实训"]):
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
                    k in card_text for k in ["开始实训", "继续挑战", "去完成", "进入实训"]
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


def run_classroom_cruise(
    page: Page,
    max_tasks: int = 10,
    min_duration: int = 60,
    auto_next: bool = True,
    solver_callback: Optional[Callable[[Page, Any], bool]] = None,
) -> Dict[str, Any]:
    """课堂大作业全自动巡航编排执行入口。

    Args:
        page: Playwright Page 实例 (主作业列表页)
        max_tasks: 最大连续执行的大题数量上限 (默认 10)
        min_duration: 每道关卡控速最小作答时长 (秒，默认 60，传 0 直出)
        auto_next: 评测通过后是否自动流转至下一关 (默认 True)
        solver_callback: 可选的自定义单关求解回调

    Returns:
        dict: 全流程作业通关汇总报表
    """
    cruise_start = time.time()
    logger.info(f">>> 启动课堂大作业全自动巡航编排 (最大大题数: {max_tasks}, 关卡控速: {min_duration}s) <<<")

    tasks = scan_classroom_tasks(page)
    total_found = len(tasks)
    pending_tasks = [t for t in tasks if not t["is_completed"] and t["button"] is not None]

    logger.info(f"巡航概况: 发现总大题 {total_found} 道，其中待完成 {len(pending_tasks)} 道")

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
                else:
                    # 默认使用现有复合流水线评测
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
