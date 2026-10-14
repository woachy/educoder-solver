"""智能防刷控速与拟真思考控制器 (Intelligent Pacing & Thinking Controller).

头歌教师端会审查答题耗时，严禁秒刷！
本模块提供智能控速体系：
1. 记录开题打卡时间戳。
2. 提交前智能计算已耗时与目标时长（底线时长 + 拟真随机抖动）的差额。
3. 差额等待期间平滑延时，绝不无故死等整段时长。
4. 每隔 15 秒向页面注入拟真微交互心跳（平滑微滚动），防止前端挂机或被识别为静止机器人。
5. 提供 rich 拟真思考倒计时交互式进度条，支持传 0 直出供快速自测。
"""

import json
import os
import random
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from playwright.sync_api import Page
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from src.config import config
from src.utils.logger import logger


# 项目根目录与持久化缓存路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CACHE_FILE = PROJECT_ROOT / ".cache" / "pacing_state.json"


class PacingController:
    """智能思考控速器"""

    HEARTBEAT_INTERVAL: float = 15.0  # 拟真页面心跳间隔 (秒)
    HEARTBEAT_SCRIPT: str = "window.scrollBy(0, 15); setTimeout(() => window.scrollBy(0, -15), 200)"
    MAX_CACHE_AGE_SECONDS: float = 7200.0  # 缓存最大有效时间 (2 小时)

    def __init__(
        self,
        default_min_duration: Optional[int] = None,
        cache_file: Optional[Path] = None,
    ):
        self.default_min_duration = (
            default_min_duration if default_min_duration is not None else config.safety.min_task_duration
        )
        self.cache_file = cache_file if cache_file is not None else DEFAULT_CACHE_FILE
        self._task_start_times: Dict[str, float] = {}
        self._default_start_time: Optional[float] = None
        self.console = Console()

    @staticmethod
    def _normalize_task_id(task_id: Any) -> Optional[str]:
        """对 URL（如包含 educoder.net）提取干净的 path 作为 key，同时保留原始 key。"""
        if not task_id:
            return None
        if not isinstance(task_id, str):
            task_id = str(task_id)
        task_id = task_id.strip()
        if not task_id:
            return None
        try:
            if "educoder.net" in task_id or "://" in task_id:
                parsed = urllib.parse.urlparse(task_id)
                path = parsed.path.rstrip("/")
                if path:
                    return path
            elif task_id.startswith("/") and ("?" in task_id or "#" in task_id):
                parsed = urllib.parse.urlparse(task_id)
                path = parsed.path.rstrip("/")
                if path:
                    return path
        except Exception:
            pass
        return task_id

    def _load_cache(self, now: Optional[float] = None) -> Dict[str, float]:
        """读取持久化缓存并过滤超过 2 小时的过期记录。"""
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                data = json.loads(content)
                if not isinstance(data, dict):
                    return {}
                current_time = now if now is not None else time.time()
                valid_data: Dict[str, float] = {}
                for k, v in data.items():
                    if isinstance(v, (int, float)):
                        age = current_time - v
                        if -60.0 <= age <= self.MAX_CACHE_AGE_SECONDS:
                            valid_data[str(k)] = float(v)
                return valid_data
        except Exception as e:
            logger.debug(f"读取 pacing_state 缓存失败: {e}")
            return {}

    def _save_cache(self, data: Dict[str, float]) -> None:
        """原子写入持久化缓存文件。"""
        temp_file = None
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.cache_file.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex}")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.cache_file)
        except Exception as e:
            logger.debug(f"原子写入 pacing_state.json 失败: {e}")
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink(missing_ok=True)
                except Exception:
                    pass

    def start_task(self, task_id: Optional[str] = None) -> float:
        """记录开题打卡时间戳至内存，并同步写入持久化缓存。

        Args:
            task_id: 可选的关卡或任务唯一标识符

        Returns:
            float: 记录的时间戳
        """
        now = time.time()
        if task_id is not None and not isinstance(task_id, str):
            task_id = str(task_id)

        norm_id = self._normalize_task_id(task_id) if task_id else None

        if task_id:
            self._task_start_times[task_id] = now
            if norm_id and norm_id != task_id:
                self._task_start_times[norm_id] = now
        else:
            self._default_start_time = now

        # 同步写入持久化缓存
        try:
            cache = self._load_cache(now=now)
            key = task_id or "default"
            cache[key] = now
            if norm_id and norm_id != key:
                cache[norm_id] = now
            self._save_cache(cache)
        except Exception as e:
            logger.debug(f"持久化开题打卡时间戳失败: {e}")

        logger.debug(f"已记录开题打卡时间戳: task_id={task_id or 'default'}, time={now}")
        return now

    def get_elapsed_time(self, task_id: Optional[str] = None) -> float:
        """获取当前任务自开题以来已经消耗的秒数。
        优先查内存，未命中则查 .cache/pacing_state.json。过滤超过 2 小时的过期记录。
        """
        if task_id is not None and not isinstance(task_id, str):
            task_id = str(task_id)

        now = time.time()
        norm_id = self._normalize_task_id(task_id) if task_id else None

        # 1. 优先查内存
        start = None
        if task_id:
            if task_id in self._task_start_times:
                start = self._task_start_times[task_id]
            elif norm_id and norm_id in self._task_start_times:
                start = self._task_start_times[norm_id]
        elif self._default_start_time is not None:
            start = self._default_start_time

        # 检查内存中的记录是否过期 (> 2小时)
        if start is not None:
            age = now - start
            if age > self.MAX_CACHE_AGE_SECONDS or age < -60.0:
                logger.debug(f"内存打卡记录已过期: task_id={task_id}, age={age:.1f}s")
                start = None
                if task_id:
                    self._task_start_times.pop(task_id, None)
                    if norm_id:
                        self._task_start_times.pop(norm_id, None)
                else:
                    self._default_start_time = None

        # 2. 内存未命中或已过期，则查持久化缓存
        if start is None:
            cache = self._load_cache(now=now)
            key = task_id or "default"
            if key in cache:
                start = cache[key]
            elif norm_id and norm_id in cache:
                start = cache[norm_id]

            # 若持久化缓存命中，写回内存以便后续快速访问
            if start is not None:
                if task_id:
                    self._task_start_times[task_id] = start
                    if norm_id:
                        self._task_start_times[norm_id] = start
                else:
                    self._default_start_time = start

        if start is None:
            # 若未曾打卡或已过期，以当前为起点，即耗时 0
            return 0.0

        return max(0.0, now - start)

    def clear_task(self, task_id: Optional[str] = None) -> None:
        """清除内存和持久化缓存中的对应记录。

        Args:
            task_id: 可选的关卡或任务唯一标识符
        """
        if task_id is not None and not isinstance(task_id, str):
            task_id = str(task_id)

        norm_id = self._normalize_task_id(task_id) if task_id else None

        # 1. 清理内存记录
        if task_id:
            mem_keys = set()
            for k in list(self._task_start_times.keys()):
                if k == task_id or (norm_id and k == norm_id):
                    mem_keys.add(k)
                elif norm_id and self._normalize_task_id(k) == norm_id:
                    mem_keys.add(k)
            for k in mem_keys:
                self._task_start_times.pop(k, None)
        else:
            self._default_start_time = None

        # 2. 清理持久化缓存记录
        try:
            cache = self._load_cache()
            key = task_id or "default"
            keys_to_remove = set()
            for k in list(cache.keys()):
                if k == key or (norm_id and k == norm_id):
                    keys_to_remove.add(k)
                elif norm_id and self._normalize_task_id(k) == norm_id:
                    keys_to_remove.add(k)

            if keys_to_remove:
                for k in keys_to_remove:
                    cache.pop(k, None)
                self._save_cache(cache)
                logger.debug(f"已清理打卡缓存记录: {keys_to_remove}")
        except Exception as e:
            logger.debug(f"清理持久化缓存记录失败: {e}")

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
