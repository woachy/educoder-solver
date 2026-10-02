"""自动化评测监听与自愈熔断器 (Evaluation Action & Circuit Breaker).

负责头歌实训关卡评测流程的生命周期控制：
1. 遮罩清理：交互前清理可能遮挡评测按钮的各类弹窗与遮罩层 (dismiss_blocking_overlays)。
2. 两阶段防竞态监听：
   - 第一阶段（等待启动）：点击评测按钮后保持 500ms~800ms 观察期，直到出现 loading 或评测请求已发出；
   - 第二阶段（等待完成）：轮询监控 loading 消失，并且比对评测结果内容是否已产生新变化，避免读到上一关的历史旧结果。
3. 高信息密度回执：提纯 passed, pass_ratio, expected, actual, diff_hint, error_output 等结构化指标。
4. 熔断保护 (Circuit Breaker)：严格遵守 AGENTS.md 红线，跟踪连续报错历史。
   若连续 3 次评测报错完全相同，主动触发熔断停止并告警，禁止死循环消耗评测配额。
5. 自动流转：支持识别并点击“下一关”按钮。
"""

import re
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import ElementHandle, Page

from src.config import config
from src.executor.diff_extractor import extract_testcase_diff
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.utils.delay import random_delay
from src.utils.logger import logger


class EvaluationManager:
    """实训评测管理器与自愈熔断器"""

    EVAL_BUTTON_SELECTORS = [
        "button:has-text('评测')",
        "button:has-text('提交')",
        "button:has-text('立即评测')",
        "a:has-text('评测')",
        ".evaluate-btn",
        ".shixun-eval-btn",
        ".btn-test",
        ".btn-eval",
        "button.ant-btn:has-text('评测')",
        "button.el-button:has-text('评测')",
        ".submit-btn",
    ]

    NEXT_LEVEL_SELECTORS = [
        ".evaluate-result-container a:has-text('下一关')",
        ".evaluate-result-container button:has-text('下一关')",
        "button:has-text('下一关')",
        "a:has-text('下一关')",
        "button:has-text('进入下一关')",
        ".next-stage-btn",
        ".next-btn",
        ".btn-next",
        "button.ant-btn:has-text('下一关')",
        "button.el-button:has-text('下一关')",
    ]

    LOADING_SELECTORS = [
        ".ant-spin-spinning",
        ".el-loading-mask",
        ".loading-mask",
        ".eval-loading",
        ".evaluating",
        ".submitting",
        ".loading",
        ".ant-btn-loading",
    ]

    RESULT_CONTAINER_SELECTORS = [
        ".evaluate-result-container",
        ".test-result",
        ".console-output",
        ".eval-result",
        ".shixun-result",
        ".terminal-window",
        ".output-box",
        ".test-cases",
        ".run-result",
        ".log-content",
        "pre.output",
        "#console",
    ]

    def __init__(self, max_consecutive_unchanged_errors: Optional[int] = None):
        self.max_unchanged_errors = (
            max_consecutive_unchanged_errors
            if max_consecutive_unchanged_errors is not None
            else config.safety.max_consecutive_unchanged_errors
        )
        self.error_history: List[str] = []
        self.circuit_broken: bool = False
        self.total_eval_count: int = 0

    def reset_circuit_breaker(self) -> None:
        """重置熔断器状态与报错历史队列"""
        self.error_history.clear()
        self.circuit_broken = False
        logger.info("已重置评测报错历史与熔断保护状态")

    def record_error(self, error_message: str) -> bool:
        """记录一次评测报错信息，并判定是否触发熔断。

        Args:
            error_message: 评测返回的错误详情文本

        Returns:
            bool: 若触发熔断返回 True，否则返回 False
        """
        norm_err = (error_message or "").strip()
        self.error_history.append(norm_err)

        if not norm_err:
            return False

        # 检查队列尾部是否连续 N 次报错完全相同
        if len(self.error_history) >= self.max_unchanged_errors:
            recent_errors = self.error_history[-self.max_unchanged_errors :]
            if all(e == norm_err for e in recent_errors):
                self.circuit_broken = True
                logger.error(
                    f"【安全熔断触发】检测到连续 {self.max_unchanged_errors} 次评测返回完全一致的错误信息！\n"
                    f"报错摘要: {norm_err[:200]}...\n"
                    "已强制终止自动评测以保护平台配额，请人工检查算法逻辑或页面状态。"
                )
                return True

        return False

    def find_eval_button(self, page: Page) -> Optional[ElementHandle]:
        """定位评测/提交按钮"""
        if not page:
            return None

        for selector in self.EVAL_BUTTON_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    return btn
            except Exception:
                continue

        # 尝试通过 locator
        try:
            loc = page.locator("button:has-text('评测')").first
            if loc and loc.count() > 0 and loc.is_visible():
                return loc.element_handle()
        except Exception:
            pass

        return None

    def get_result_snapshot(self, page: Page) -> str:
        """获取当前页面评测结果区域的内容快照，用于两阶段防竞态比对"""
        if not page:
            return ""
        try:
            texts = []
            for sel in self.RESULT_CONTAINER_SELECTORS:
                try:
                    container = page.query_selector(sel)
                    if container and container.is_visible():
                        t = container.inner_text().strip()
                        if t:
                            texts.append(t)
                except Exception:
                    pass
            return "||".join(texts)
        except Exception:
            return ""

    def _is_eval_loading(self, page: Page) -> bool:
        """检测页面是否处于评测 loading 态"""
        if not page:
            return False

        for sel in self.LOADING_SELECTORS:
            try:
                loader = page.query_selector(sel)
                if loader and loader.is_visible():
                    return True
            except Exception:
                continue

        try:
            btn = self.find_eval_button(page)
            if btn:
                cls = btn.get_attribute("class") or ""
                if "loading" in cls or "is-loading" in cls or "ant-btn-loading" in cls:
                    return True
        except Exception:
            pass

        return False

    def _is_eval_btn_ready(self, page: Page) -> bool:
        """检查评测按钮是否已处于非禁用就绪态"""
        btn = self.find_eval_button(page)
        if not btn:
            return True
        try:
            disabled = btn.get_attribute("disabled")
            btn_class = btn.get_attribute("class") or ""
            if not disabled and "disabled" not in btn_class and "loading" not in btn_class:
                return True
        except Exception:
            pass
        return False

    def wait_for_eval_completion(
        self,
        page: Page,
        timeout_seconds: int = 60,
        pre_snapshot: str = "",
    ) -> bool:
        """两阶段防竞态监听评测状态直到完成或超时。

        第一阶段（等待启动）：
        点击评测按钮后，保持 500ms~800ms 观察期，直到出现 loading 状态或评测请求发出。

        第二阶段（等待完成）：
        轮询等待 loading 消失，并且比对评测结果内容是否已产生新变化（避免读到上一关的历史旧结果）。
        """
        start_time = time.time()
        logger.info(f"等待评测启动与完成，超时上限={timeout_seconds}s...")

        # 第一阶段：观察等待启动 (500ms ~ 800ms 观察期)
        loading_detected = False
        phase1_start = time.time()
        while time.time() - phase1_start < 0.8:
            time.sleep(0.1)
            # 优先检测是否有通关弹窗快速出现
            try:
                modal = page.query_selector(".evaluate-result-container")
                if modal and modal.is_visible():
                    logger.info("第一阶段：检测到评测通关结果弹窗快速生成")
                    return True
            except Exception:
                pass

            if self._is_eval_loading(page):
                loading_detected = True
                logger.debug("第一阶段：已检测到评测 loading 加载动画启动")
                break

        # 第二阶段：等待评测执行完成并校验结果新鲜度
        while time.time() - start_time < timeout_seconds:
            # 检查是否有通关弹窗
            try:
                modal = page.query_selector(".evaluate-result-container")
                if modal and modal.is_visible():
                    logger.info("第二阶段：检测到评测通关结果弹窗 .evaluate-result-container")
                    return True
            except Exception:
                pass

            is_loading = self._is_eval_loading(page)

            if not is_loading:
                btn_ready = self._is_eval_btn_ready(page)
                current_snapshot = self.get_result_snapshot(page)
                has_new_result = (current_snapshot != pre_snapshot) if pre_snapshot else bool(current_snapshot)

                if btn_ready and has_new_result:
                    logger.info("第二阶段：评测加载结束，结果内容已产生有效更新且按钮就绪")
                    return True

                if loading_detected and btn_ready:
                    logger.info("第二阶段：评测 loading 动画已结束，按钮已恢复可用")
                    return True

                # 若未检测到 loading 也未捕获到旧快照，按钮就绪即视为完成
                if not pre_snapshot and btn_ready:
                    return True

            time.sleep(0.4)

        logger.warning(f"评测等待超过 {timeout_seconds} 秒，可能未完成或超时")
        return False

    def extract_eval_results(self, page: Page) -> Dict[str, Any]:
        """从页面控制台和结果区域提取评测结果、通过率与报错文本。

        集成了 extract_testcase_diff 提纯核心差异，同时保留旧版兼容字段。
        """
        # 使用高密度 Diff 提取器
        diff_res = extract_testcase_diff(page)

        passed = diff_res["passed"]
        pass_ratio = diff_res["pass_ratio"]
        error_output = diff_res["error_msg"]
        stdout = diff_res["stdout_msg"]
        expected = diff_res["expected"]
        actual = diff_res["actual"]
        diff_hint = diff_res["diff_hint"]

        # 兜底旧版页面通用提取逻辑 (若 diff_extractor 未提取到详细信息)
        if not diff_hint and not error_output and not stdout:
            full_output = ""
            for sel in self.RESULT_CONTAINER_SELECTORS:
                try:
                    container = page.query_selector(sel)
                    if container and container.is_visible():
                        text = container.inner_text()
                        if text and len(text.strip()) > 0:
                            full_output += "\n" + text.strip()
                except Exception:
                    continue

            full_output = full_output.strip()
            if full_output:
                diff_hint = "检测到评测控制台输出"
                stdout = full_output

        raw_output = f"Expected: {expected}\nActual: {actual}\nHint: {diff_hint}" if (expected or actual) else stdout

        return {
            "passed": passed,
            "pass_ratio": pass_ratio,
            "error_output": error_output,
            "stdout": stdout,
            "raw_output": raw_output,
            "expected": expected,
            "actual": actual,
            "diff_hint": diff_hint,
            "stdout_msg": stdout,
            "error_msg": error_output,
        }

    def trigger_and_wait_eval(self, page: Page, timeout_seconds: int = 60) -> Dict[str, Any]:
        """触发评测并等待结果回执，内置两阶段防竞态监听与熔断保护。

        Args:
            page: Playwright Page 实例
            timeout_seconds: 最长等待秒数，默认 60s

        Returns:
            dict: 评测回执结果字典
        """
        # 1. 熔断前置检查
        if self.circuit_broken:
            msg = (
                f"【熔断保护生效中】连续 {self.max_unchanged_errors} 次评测返回相同报错，已主动阻断提交。"
                "请先修复逻辑或调用 reset_circuit_breaker() 后重试。"
            )
            logger.error(msg)
            return {
                "success": False,
                "passed": False,
                "pass_ratio": "",
                "error_output": self.error_history[-1] if self.error_history else "",
                "stdout": "",
                "expected": "",
                "actual": "",
                "diff_hint": "触发安全熔断保护，已终止评测",
                "stdout_msg": "",
                "error_msg": self.error_history[-1] if self.error_history else "",
                "circuit_broken": True,
                "message": msg,
            }

        # 2. 交互前自动清理遮挡弹窗与拦截指针事件的遮罩
        dismiss_blocking_overlays(page)

        # 3. 记录前置评测结果快照 (用于两阶段防竞态比对，避免误读取旧结果)
        pre_snapshot = self.get_result_snapshot(page)

        # 4. 定位评测按钮
        eval_btn = self.find_eval_button(page)
        if not eval_btn:
            msg = "页面中未定位到评测或提交按钮"
            logger.error(msg)
            return {
                "success": False,
                "passed": False,
                "pass_ratio": "",
                "error_output": "",
                "stdout": "",
                "expected": "",
                "actual": "",
                "diff_hint": msg,
                "stdout_msg": "",
                "error_msg": "",
                "circuit_broken": self.circuit_broken,
                "message": msg,
            }

        # 5. 拟真点击评测按钮
        logger.info("正在拟真点击评测按钮...")
        random_delay(0.3, 0.8)
        try:
            eval_btn.click()
            self.total_eval_count += 1
        except Exception as e:
            logger.error(f"点击评测按钮失败: {e}")
            return {
                "success": False,
                "passed": False,
                "pass_ratio": "",
                "error_output": str(e),
                "stdout": "",
                "expected": "",
                "actual": "",
                "diff_hint": f"点击评测异常: {e}",
                "stdout_msg": "",
                "error_msg": str(e),
                "circuit_broken": self.circuit_broken,
                "message": f"点击评测按钮异常: {e}",
            }

        # 6. 两阶段防竞态监听评测状态结束
        self.wait_for_eval_completion(page, timeout_seconds=timeout_seconds, pre_snapshot=pre_snapshot)

        # 7. 提取评测回执
        eval_result = self.extract_eval_results(page)
        passed = eval_result.get("passed", False)
        error_output = eval_result.get("error_output", "")
        pass_ratio = eval_result.get("pass_ratio", "")
        stdout = eval_result.get("stdout", "")
        expected = eval_result.get("expected", "")
        actual = eval_result.get("actual", "")
        diff_hint = eval_result.get("diff_hint", "")
        stdout_msg = eval_result.get("stdout_msg", stdout)
        error_msg = eval_result.get("error_msg", error_output)

        # 8. 自愈熔断状态机更新
        if passed:
            self.error_history.clear()
            msg = f"评测全部通过！通过比例: {pass_ratio or '100%'}"
            logger.success(msg)
        else:
            is_broken = self.record_error(error_output)
            msg = (
                f"评测未通过 (通过率: {pass_ratio or '0'})，连续相同错误次数: {len(self.error_history)}"
                if not is_broken
                else f"评测未通过且已触发熔断保护 (已达连续 {self.max_unchanged_errors} 次完全相同报错)"
            )
            logger.warning(msg)

        return {
            "success": True,
            "passed": passed,
            "pass_ratio": pass_ratio,
            "error_output": error_output,
            "stdout": stdout,
            "expected": expected,
            "actual": actual,
            "diff_hint": diff_hint,
            "stdout_msg": stdout_msg,
            "error_msg": error_msg,
            "circuit_broken": self.circuit_broken,
            "message": msg,
        }

    def trigger_next_level(self, page: Page) -> bool:
        """识别并点击‘下一关’按钮，流转至后续任务。

        Returns:
            bool: 成功点击返回 True，未找到或点击失败返回 False
        """
        logger.info("正在检索‘下一关’按钮...")
        if not page:
            return False

        next_btn = None
        for selector in self.NEXT_LEVEL_SELECTORS:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    next_btn = btn
                    break
            except Exception:
                continue

        if not next_btn:
            try:
                loc = page.locator("button:has-text('下一关'), a:has-text('下一关')").first
                if loc and loc.count() > 0 and loc.is_visible():
                    next_btn = loc.element_handle()
            except Exception:
                pass

        if next_btn:
            random_delay(0.5, 1.0)
            try:
                next_btn.click()
                logger.success("已成功点击‘下一关’，页面正在流转...")
                return True
            except Exception as e:
                logger.error(f"点击‘下一关’按钮失败: {e}")
                return False

        logger.warning("未检测到可点击的‘下一关’按钮")
        return False
