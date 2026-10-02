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
from src.extractor.base import QuestionData
from src.utils.logger import logger


def run_solve_cycle(
    page: Page,
    code: str,
    target_only: bool = True,
    auto_next: bool = False,
    timeout: int = 60,
    eval_manager: Optional[EvaluationManager] = None,
    question_data: Optional[QuestionData] = None,
) -> Dict[str, Any]:
    """在单个页面会话中执行“清理弹窗 -> 注入代码 -> 评测监听 -> 提纯Diff -> 流转下一关”完整闭环。

    Args:
        page: Playwright Page 页面实例
        code: 待注入的代码字符串
        target_only: 是否仅替换 Begin-End 靶心区域 (默认 True)
        auto_next: 评测全绿后是否自动点击“下一关” (默认 False)
        timeout: 评测等待超时上限 (秒，默认 60)
        eval_manager: 可选的 EvaluationManager 实例 (用于延续熔断状态)
        question_data: 可选的预探测实训题目数据

    Returns:
        dict: 结构化低熵流水线回执字典:
            - success (bool): 全流程交互是否执行成功
            - passed (bool): 评测是否全部通过
            - pass_ratio (str): 测试用例通过比例 (如 "1/1", "0/2")
            - expected (str): 预期输出
            - actual (str): 实际输出
            - diff_hint (str): 高密度差异提示
            - stdout_msg (str): 控制台标准输出
            - error_msg (str): 错误异常栈
            - circuit_broken (bool): 是否触发连续相同报错熔断
            - next_level_triggered (bool): 是否成功点击进入下一关
            - overlays_dismissed (int): 清理的遮罩/弹窗数量
            - elapsed_seconds (float): 流水线执行耗时 (秒)
            - injection (dict): 代码注入元信息
            - message (str): 状态说明
    """
    start_time = time.time()
    logger.info(">>> 启动复合答题流水线 (Solve Cycle) <<<")

    eval_mgr = eval_manager or EvaluationManager()

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
            "injection": inject_res,
            "message": err_msg,
        }

    # 3. 触发评测并两阶段监听回执
    eval_res = eval_mgr.trigger_and_wait_eval(page, timeout_seconds=timeout)

    passed = eval_res.get("passed", False)
    next_level_triggered = False

    # 4. 若评测全部通过且开启了 auto_next，自动点击下一关
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
        },
        "message": eval_res.get("message", ""),
    }
