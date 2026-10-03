"""智能防刷控速与拟真思考控制器 (Intelligent Pacing & Thinking Controller).

头歌教师端会审查答题耗时，严禁秒刷！
本模块提供智能控速体系：
1. 记录开题打卡时间戳。
2. 提交前智能计算已耗时与目标时长（底线时长 + 拟真随机抖动）的差额。
3. 差额等待期间平滑延时，绝不无故死等整段时长。
4. 每隔 15 秒向页面注入拟真微交互心跳（平滑微滚动），防止前端挂机或被识别为静止机器人。
5. 提供 rich 拟真思考倒计时交互式进度条，支持传 0 直出供快速自测。
"""

import random
import time
from typing import Dict, Optional, Tuple
from playwright.sync_api import Page
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from src.config import config
from src.utils.logger import logger


class PacingController:
    """智能思考控速器"""

    HEARTBEAT_INTERVAL: float = 15.0  # 拟真页面心跳间隔 (秒)
    HEARTBEAT_SCRIPT: str = "window.scrollBy(0, 15); setTimeout(() => window.scrollBy(0, -15), 200)"

    def __init__(self, default_min_duration: Optional[int] = None):
        self.default_min_duration = (
            default_min_duration if default_min_duration is not None else config.safety.min_task_duration
        )
        self._task_start_times: Dict[str, float] = {}
        self._default_start_time: Optional[float] = None
        self.console = Console()

    def start_task(self, task_id: Optional[str] = None) -> float:
        """记录开题打卡时间戳。

        Args:
            task_id: 可选的关卡或任务唯一标识符

        Returns:
            float: 记录的时间戳
        """
        now = time.time()
        if task_id:
            self._task_start_times[task_id] = now
        else:
            self._default_start_time = now
        logger.debug(f"已记录开题打卡时间戳: task_id={task_id or 'default'}, time={now}")
        return now

    def get_elapsed_time(self, task_id: Optional[str] = None) -> float:
        """获取当前任务自开题以来已经消耗的秒数。"""
        start = None
        if task_id and task_id in self._task_start_times:
            start = self._task_start_times[task_id]
        elif self._default_start_time is not None:
            start = self._default_start_time

        if start is None:
            # 若未曾打卡，以当前为起点，即耗时 0
            return 0.0

        return max(0.0, time.time() - start)

    def trigger_heartbeat(self, page: Optional[Page]) -> bool:
        """向目标页面触发拟真微交互心跳（防挂机与前端活跃度保鲜）。"""
        if not page:
            return False
        try:
            if hasattr(page, "is_closed") and page.is_closed():
                return False
            if hasattr(page, "evaluate") and callable(page.evaluate):
                page.evaluate(self.HEARTBEAT_SCRIPT)
                logger.debug("已触发页面拟真交互心跳 (微滚动防挂机)")
                return True
        except Exception as e:
            logger.debug(f"触发页面拟真心跳被忽略: {e}")
        return False

    def wait_thinking_pacing(
        self,
        page: Optional[Page] = None,
        min_duration: Optional[int] = None,
        jitter_range: Tuple[int, int] = (5, 20),
        quiet: bool = False,
        task_id: Optional[str] = None,
    ) -> float:
        """智能差额思考等待。

        Args:
            page: 可选的 Playwright Page 实例 (用于发送拟真交互心跳)
            min_duration: 要求的最小作答总时长 (秒)。若 <= 0 则直接退出供自测
            jitter_range: 拟真随机抖动区间 (秒)，如 (5, 20)
            quiet: 是否静默等待 (不输出 rich 进度条)
            task_id: 可选的任务 ID

        Returns:
            float: 最终经历的总耗时 (秒)
        """
        if min_duration is None:
            min_duration = self.default_min_duration

        elapsed = self.get_elapsed_time(task_id)

        # 若 min_duration <= 0，快速自测模式直接放行
        if min_duration <= 0:
            logger.info("控速策略: min_duration <= 0，快速自测模式直接放行")
            return elapsed

        # 计算拟真抖动
        j_min = min(jitter_range)
        j_max = max(jitter_range)
        jitter = random.randint(j_min, j_max) if j_max >= j_min else 0
        target_duration = min_duration + jitter

        remaining = target_duration - elapsed
        if remaining <= 0:
            logger.info(
                f"控速策略: 当前已耗时 {elapsed:.1f}s 已满足目标时长 {target_duration:.1f}s (基础 {min_duration}s + 抖动 {jitter}s)，无需额外等待"
            )
            return elapsed

        logger.info(
            f"控速策略: 目标总耗时 {target_duration:.1f}s (基础 {min_duration}s + 拟真抖动 {jitter}s)，已过 {elapsed:.1f}s，智能补齐差额 {remaining:.1f}s..."
        )

        show_progress = (not quiet) and (not config.log.json_mode)
        start_wait = time.time()
        last_heartbeat = start_wait

        if show_progress:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]防刷控速中: {task.description}[/bold cyan]"),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("•"),
                TimeRemainingColumn(),
                console=self.console,
                transient=True,
            ) as progress:
                prog_task = progress.add_task(f"拟真思考倒计时 ({remaining:.1f}s)", total=remaining)
                while True:
                    current_wait = time.time() - start_wait
                    if current_wait >= remaining:
                        progress.update(prog_task, completed=remaining)
                        break

                    progress.update(prog_task, completed=current_wait)

                    # 心跳检查
                    if time.time() - last_heartbeat >= self.HEARTBEAT_INTERVAL:
                        self.trigger_heartbeat(page)
                        last_heartbeat = time.time()

                    sleep_step = min(0.5, remaining - current_wait)
                    time.sleep(max(0.01, sleep_step))
        else:
            # 静默等待循环
            while True:
                current_wait = time.time() - start_wait
                if current_wait >= remaining:
                    break

                if time.time() - last_heartbeat >= self.HEARTBEAT_INTERVAL:
                    self.trigger_heartbeat(page)
                    last_heartbeat = time.time()

                sleep_step = min(1.0, remaining - current_wait)
                time.sleep(max(0.01, sleep_step))

        total_elapsed = self.get_elapsed_time(task_id)
        logger.info(f"防刷控速完成，本题作答总耗时达 {total_elapsed:.1f}s，安全准予提交")
        return total_elapsed


# 全局单例控速器
pacing_controller = PacingController()
