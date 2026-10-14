"""复合答题流水线核心引擎 (Solve Pipeline Core Engine).

在单个 CDP 页面会话中一次性流转实训题闭环生命周期：
1. 清理遮挡弹窗与拦截指针事件的遮罩 (dismiss_blocking_overlays)
2. 安全备份并注入靶心代码 (inject_code, Monaco 原生 API 优先)
3. 触发两阶段防竞态评测监听 (trigger_and_wait_eval)
4. 提纯返回高密度 Diff 结果 (extract_testcase_diff)
5. 若全部通过且配置了 auto_next，自动点击下一关 (trigger_next_level)

通过会话内闭环流转，避免频繁重新握手 CDP，将单次循环执行耗时从 30s 缩减至 5~8s。
"""

import time
from typing import Any, Dict, Optional
from playwright.sync_api import Page

from src.executor.editor_action import inject_code
from src.executor.eval_action import EvaluationManager
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.executor.pacing import pacing_controller
from src.extractor.base import QuestionData
from src.utils.logger import logger


def run_solve_cycle(
    page: Page,
    code: str,
    target_only: bool = True,
    auto_next: bool = False,
    timeout: int = 60,
    min_duration: int = 0,
    eval_manager: Optional[EvaluationManager] = None,
    question_data: Optional[QuestionData] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在单个页面会话中执行“清理弹窗 -> 注入代码 -> 控速等待 -> 评测监听 -> 提纯Diff -> 流转下一关”完整闭环。

    Args:
        page: Playwright Page 页面实例
        code: 待注入的代码字符串
        target_only: 是否仅替换 Begin-End 靶心区域 (默认 True)
        auto_next: 评测全绿后是否自动点击“下一关” (默认 False)
        timeout: 评测等待超时上限 (秒，默认 60)
        min_duration: 防秒刷最小作答总时长 (秒，<= 0 直出自测)
        eval_manager: 可选的 EvaluationManager 实例 (用于延续熔断状态)
        question_data: 可选的预探测实训题目数据
        task_id: 可选的题目唯一 ID (用于控速打卡跟踪)

    Returns:
        dict: 结构化低熵流水线回执字典
    """
    start_time = time.time()
    logger.info(">>> 启动复合答题流水线 (Solve Cycle) <<<")

    eval_mgr = eval_manager or EvaluationManager()

    # 获取有效任务 ID (若未显式指定，默认取 page.url)
    effective_task_id = task_id
    if effective_task_id is None and page:
        try:
            url_val = getattr(page, "url", None)
            if url_val is not None:
                effective_task_id = str(url_val) if not isinstance(url_val, str) else url_val
        except Exception:
            effective_task_id = None

    # 1. 清理可能遮挡编辑器或评测按钮的各类弹窗与遮罩
    overlays_dismissed = dismiss_blocking_overlays(page)

    # 2. 安全备份并分级注入代码 (Monaco API 优先)
    inject_res = inject_code(
        page,
        code,
        target_only=target_only,
        question_data=question_data,
    )

    if not inject_res.get("success"):
        elapsed = round(time.time() - start_time, 2)
        err_msg = inject_res.get("message", "代码注入失败")
        logger.error(f"流水线终止：{err_msg}")
        return {
            "success": False,
            "passed": False,
            "pass_ratio": "",
            "expected": "",
            "actual": "",
            "diff_hint": f"代码注入失败: {err_msg}",
            "stdout_msg": "",
            "error_msg": err_msg,
            "circuit_broken": False,
            "next_level_triggered": False,
            "overlays_dismissed": overlays_dismissed,
            "elapsed_seconds": elapsed,
            "injection": {
                **inject_res,
                "saved": inject_res.get("saved", False),
                "commit_id": inject_res.get("commit_id", ""),
            },
            "message": err_msg,
        }

    # 3. 拟真思考防刷控速 (根据题目开题已耗时智能补足差额)
    if min_duration > 0:
        pacing_controller.wait_thinking_pacing(
            page=page,
            min_duration=min_duration,
            task_id=effective_task_id,
        )

    # 4. 触发评测并两阶段监听回执
    eval_res = eval_mgr.trigger_and_wait_eval(page, timeout_seconds=timeout)

    passed = eval_res.get("passed", False)
    next_level_triggered = False

    # 若评测全部通过，清理当前关卡的控速打卡缓存
    if passed:
        pacing_controller.clear_task(effective_task_id)

    # 5. 若评测全部通过且开启了 auto_next，自动点击下一关
    if passed and auto_next:
        logger.info("评测全部通过，正在自动流转下一关...")
        next_level_triggered = eval_mgr.trigger_next_level(page)

    elapsed = round(time.time() - start_time, 2)
    logger.info(f"<<< 复合答题流水线执行完成 (耗时: {elapsed}s, 全通过: {passed}) >>>")

    return {
        "success": eval_res.get("success", False),
        "passed": passed,
        "pass_ratio": eval_res.get("pass_ratio", ""),
        "expected": eval_res.get("expected", ""),
        "actual": eval_res.get("actual", ""),
        "diff_hint": eval_res.get("diff_hint", ""),
        "stdout_msg": eval_res.get("stdout_msg", eval_res.get("stdout", "")),
        "error_msg": eval_res.get("error_msg", eval_res.get("error_output", "")),
        "circuit_broken": eval_res.get("circuit_broken", False),
        "next_level_triggered": next_level_triggered,
        "overlays_dismissed": overlays_dismissed,
        "elapsed_seconds": elapsed,
        "injection": {
            "success": inject_res.get("success", False),
            "method_used": inject_res.get("method_used", ""),
            "backup_path": inject_res.get("backup_path", ""),
            "is_target_assembled": inject_res.get("is_target_assembled", False),
            "saved": inject_res.get("saved", False),
            "commit_id": inject_res.get("commit_id", ""),
        },
        "message": eval_res.get("message", ""),
    }
