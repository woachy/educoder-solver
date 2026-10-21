"""CDP 浏览器管理器 (Browser Manager).

负责与用户物理浏览器 (Chrome / Edge) 的 Chrome DevTools Protocol (CDP) 调试端口建立挂载，
提供端口前置探活、标签页智能捕获、会话生命周期管理与安全断开。
严格遵守 AGENTS.md 规范：
1. 任何操作前必须前置探活 localhost:9222。
2. 断开连接时严禁关闭用户物理浏览器或用户已有页面。
"""

import socket
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from src.config import config
from src.utils.logger import logger


class TargetPageNotFoundError(RuntimeError):
    """未找到目标页面异常"""
    pass


def check_cdp_available(host: Optional[str] = None, port: Optional[int] = None, timeout: float = 1.0) -> bool:
    """前置探活 CDP 端口是否开放并可连接。

    Args:
        host: 目标主机，默认读取配置 config.browser.host (127.0.0.1)
        port: 调试端口，默认读取配置 config.browser.port (9222)
        timeout: 连接超时时间 (秒)

    Returns:
        bool: 端口开放可连接返回 True，否则返回 False
    """
    target_host = host or config.browser.host
    target_port = port or config.browser.port

    try:
        with socket.create_connection((target_host, target_port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def is_classroom_page(p: Page) -> bool:
    """判定页面是否为课堂作业列表页 (排除 /detail 跳板与关卡页)"""
    try:
        import re
        u = getattr(p, "url", "")
        if not isinstance(u, str) or "educoder.net" not in u.lower():
            return False
        u = u.lower()
        if "/detail" in u or "/tasks/" in u or "/challenges" in u:
            return False
        return bool("/shixun_homework" in u or "/homeworks" in u or re.search(r"/classrooms/\d+", u))
    except Exception:
        return False


def is_springboard_page(p: Page) -> bool:
    """判定页面是否为实训跳板详情页 (/detail 或仅有开启挑战按钮的介绍大纲页)"""
    try:
        u = getattr(p, "url", "")
        if not isinstance(u, str) or "educoder.net" not in u.lower():
            return False
        u = u.lower()
        if "/classrooms" in u or "/shixun_homework" in u or "/homeworks" in u:
            return False
        if "/tasks/" in u or "/challenges" in u:
            return False
        if "/detail" in u:
            return True
        return False
    except Exception:
        return False


def is_shixun_task_page(p: Page) -> bool:
    """判定页面是否为真正的实训做题关卡页 (包含编辑器或答题容器，排除列表与跳板)"""
    try:
        u = getattr(p, "url", "")
        if not isinstance(u, str) or "educoder.net" not in u.lower():
            return False
        u = u.lower()
        if "/classrooms" in u or "/shixun_homework" in u or "/homeworks" in u:
            return False
        if "/detail" in u:
            return False
        if "/tasks/" in u or "/challenges" in u or "/shixuns/" in u:
            return True
        return False
    except Exception:
        return False


class BrowserSession:
    """基于 Playwright CDP 的浏览器会话上下文管理器。

    用法:
        with BrowserSession() as session:
            page = session.get_target_page("educoder.net")
            # 执行只读提取或拟真操作...
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: float = 1.0,
        connect_timeout_ms: Optional[int] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        self.host = host or config.browser.host
        self.port = port or config.browser.port
        self.timeout = timeout
        self.connect_timeout_ms = connect_timeout_ms or config.browser.connect_timeout_ms
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._playwright_cm: Optional[Any] = None
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None

    @property
    def cdp_url(self) -> str:
        """获取 CDP 连接 URL"""
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "BrowserSession":
        """进入上下文：执行端口探活并挂载 CDP 实例"""
        logger.info(f"正在探活 CDP 调试端口 {self.host}:{self.port}...")
        if not check_cdp_available(self.host, self.port, timeout=self.timeout):
            err_msg = (
                f"CDP 调试端口 {self.host}:{self.port} 不可达。\n"
                "请先运行启动脚本开启物理浏览器远程调试：\n"
                "  .\\scripts\\launch_browser.ps1\n"
                f"或手动启动命令:\n"
                f"  chrome.exe --remote-debugging-port={self.port} --user-data-dir=\"C:\\ChromeDebugProfile\""
            )
            logger.error(err_msg)
            raise ConnectionError(err_msg)

        logger.info(f"CDP 端口探活成功，正在连接 {self.cdp_url} ...")
        self._playwright_cm = sync_playwright()
        self.playwright = self._playwright_cm.start()

        retries = max(1, self.max_retries)
        for attempt in range(1, retries + 1):
            try:
                self.browser = self.playwright.chromium.connect_over_cdp(
                    self.cdp_url,
                    timeout=self.connect_timeout_ms,
                )
                logger.success("已成功通过 CDP 挂载物理浏览器会话")
                return self
            except Exception as e:
                if attempt < retries:
                    delay = self.retry_delay * attempt
                    logger.warning(
                        f"CDP 连接失败 (尝试 {attempt}/{retries}): {e}，将在 {delay:.1f} 秒后重试..."
                    )
                    time.sleep(delay)
                else:
                    self.__exit__(None, None, None)
                    err_msg = (
                        f"连接 CDP 失败 (已重试 {retries} 次): {str(e)}\n"
                        "请确认物理浏览器已正常启动且远程调试端口处于监听状态：\n"
                        "  .\\scripts\\launch_browser.ps1\n"
                        f"或手动启动命令:\n"
                        f"  chrome.exe --remote-debugging-port={self.port} --user-data-dir=\"C:\\ChromeDebugProfile\""
                    )
                    logger.error(err_msg)
                    raise ConnectionError(err_msg) from e

        return self

    @property
    def pages(self) -> List[Page]:
        """获取当前浏览器中所有上下文的所有标签页列表"""
        all_pages: List[Page] = []
        if self.browser:
            for context in self.browser.contexts:
                all_pages.extend(context.pages)
        return all_pages

    def list_pages(self) -> List[Dict[str, str]]:
        """列出所有已打开标签页的标题与 URL"""
        result = []
        for p in self.pages:
            try:
                result.append({"title": p.title(), "url": p.url})
            except Exception:
                result.append({"title": "<unknown>", "url": "<unknown>"})
        return result

    def get_target_page(
        self,
        url_keyword: str = "educoder.net",
        fallback_first: bool = True,
        prefer_type: str = "any",
        auto_penetrate: bool = False,
    ) -> Page:
        """优先定位包含指定关键字的目标标签页。

        Args:
            url_keyword: 匹配的 URL 或标题关键字，默认 'educoder.net'
            fallback_first: 若未找到匹配标签页，是否容错回退至第一个可用标签页
            prefer_type: 页面偏好类型，可选值:
                - 'any': 保持默认优先级（优先实训关卡，其次跳板详情，其次作业列表）
                - 'classroom': 优先匹配课堂作业列表页（排除 /detail 与 /tasks/），未找到才回退
                - 'springboard': 优先匹配实训跳板详情页（/detail 或仅有开启挑战按钮的介绍页）
                - 'shixun': 优先匹配真正的做题关卡页（含编辑器或答题容器），未找到时匹配跳板详情页，最后回退作业列表页
            auto_penetrate: 若命中的页面处于跳板详情页，是否自动调用穿透逻辑直达关卡 IDE

        Returns:
            Page: 目标页面实例

        Raises:
            TargetPageNotFoundError: 未找到匹配标签页且无法回退时抛出
        """
        import re

        current_pages = self.pages
        if not current_pages:
            raise TargetPageNotFoundError("当前浏览器中未检测到任何已打开的标签页。")

        # 1. 若用户显式指定了自定义关键字（非默认 educoder.net），优先精准匹配
        if url_keyword.lower() != "educoder.net":
            for page in current_pages:
                try:
                    if url_keyword.lower() in page.url.lower() or url_keyword.lower() in page.title().lower():
                        logger.info(f"已精准匹配自定义目标页面: [{page.title()}]({page.url})")
                        if auto_penetrate and is_springboard_page(page):
                            from src.executor.classroom_orchestrator import penetrate_detail_springboard
                            ctx = getattr(page, "context", None) or (self.browser.contexts[0] if self.browser and self.browser.contexts else None)
                            page = penetrate_detail_springboard(page, ctx)
                        return page
                except Exception:
                    continue

        p_type = (prefer_type or "any").lower()

        # 2. 根据 prefer_type 优先级进行定向解耦匹配
        matched_page = None

        if p_type == "classroom":
            # 优先匹配课堂作业列表页
            for page in current_pages:
                if is_classroom_page(page):
                    try:
                        logger.info(f"已精准匹配课堂作业列表页面: [{page.title()}]({page.url})")
                    except Exception:
                        pass
                    matched_page = page
                    break
            if not matched_page:
                # 回退：实训做题关卡 -> 跳板详情页
                for page in current_pages:
                    if is_shixun_task_page(page):
                        matched_page = page
                        break
            if not matched_page:
                for page in current_pages:
                    if is_springboard_page(page):
                        matched_page = page
                        break

        elif p_type == "springboard":
            # 优先匹配跳板详情页
            for page in current_pages:
                if is_springboard_page(page):
                    try:
                        logger.info(f"已精准匹配实训跳板详情页面: [{page.title()}]({page.url})")
                    except Exception:
                        pass
                    matched_page = page
                    break
            if not matched_page:
                for page in current_pages:
                    if is_shixun_task_page(page):
                        matched_page = page
                        break
            if not matched_page:
                for page in current_pages:
                    if is_classroom_page(page):
                        matched_page = page
                        break

        elif p_type == "shixun":
            # 优先匹配真正关卡做题页 (排除跳板与列表)
            for page in current_pages:
                if is_shixun_task_page(page):
                    try:
                        logger.info(f"已精准匹配实训关卡做题页面: [{page.title()}]({page.url})")
                    except Exception:
                        pass
                    matched_page = page
                    break
            # 关卡做题页未命中时，尝试匹配跳板详情页（便于后续穿透）
            if not matched_page:
                for page in current_pages:
                    if is_springboard_page(page):
                        try:
                            logger.info(f"关卡做题页未命中，匹配到实训跳板详情页面: [{page.title()}]({page.url})")
                        except Exception:
                            pass
                        matched_page = page
                        break
            # 最后回退至课堂列表页
            if not matched_page:
                for page in current_pages:
                    if is_classroom_page(page):
                        matched_page = page
                        break

        else:
            # prefer_type == 'any'：优先做题关卡 -> 课堂作业列表 -> 跳板详情
            for page in current_pages:
                if is_shixun_task_page(page):
                    matched_page = page
                    break
            if not matched_page:
                for page in current_pages:
                    if is_classroom_page(page):
                        matched_page = page
                        break
            if not matched_page:
                for page in current_pages:
                    if is_springboard_page(page):
                        matched_page = page
                        break

        if matched_page:
            if auto_penetrate and is_springboard_page(matched_page):
                logger.info(f"已开启 auto_penetrate=True，正在穿透跳板页面 [{matched_page.url}]...")
                from src.executor.classroom_orchestrator import penetrate_detail_springboard
                ctx = getattr(matched_page, "context", None) or (self.browser.contexts[0] if self.browser and self.browser.contexts else None)
                matched_page = penetrate_detail_springboard(matched_page, ctx)
            return matched_page

        # 3. 再次按 URL 包含关键字匹配 (优先非纯 /classrooms 总览页)
        for page in current_pages:
            try:
                u = page.url.lower()
                if url_keyword.lower() in u and not u.rstrip("/").endswith("/classrooms"):
                    logger.info(f"已匹配目标页面 (URL匹配): [{page.title()}]({page.url})")
                    return page
            except Exception:
                continue

        # 4. 按标题包含关键字匹配
        for page in current_pages:
            try:
                if url_keyword.lower() in page.title().lower():
                    logger.info(f"已匹配目标页面 (标题匹配): [{page.title()}]({page.url})")
                    return page
            except Exception:
                continue

        # 5. 兜底匹配任意包含 url_keyword 的页面
        for page in current_pages:
            try:
                if url_keyword.lower() in page.url.lower():
                    logger.info(f"已匹配目标页面 (兜底URL匹配): [{page.title()}]({page.url})")
                    return page
            except Exception:
                continue

        # 未找到目标页面，记录已打开的所有页面并提供容错
        page_list = self.list_pages()
        logger.warning(
            f"未找到包含 '{url_keyword}' 的标签页。\n"
            f"当前已打开的标签页列表 ({len(page_list)} 个):\n"
            + "\n".join([f"  - [{p['title']}] {p['url']}" for p in page_list])
        )

        if fallback_first and current_pages:
            fallback_page = current_pages[0]
            logger.warning(f"容错回退使用第一个标签页: [{fallback_page.title()}]({fallback_page.url})")
            return fallback_page

        raise TargetPageNotFoundError(
            f"未找到包含 '{url_keyword}' 的标签页。已打开页面: {page_list}"
        )

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """安全退出：只断开 CDP 客户端连接，绝对禁止关闭物理浏览器或页面"""
        logger.debug("正在安全断开 CDP 客户端连接...")
        if self.browser:
            try:
                # 仅断开 CDP 连接，外部物理浏览器进程与所有标签页保持原样
                self.browser.close()
            except Exception as e:
                logger.debug(f"断开 CDP 连接异常 (安全忽略): {e}")
            finally:
                self.browser = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                logger.debug(f"关闭 Playwright 实例异常 (安全忽略): {e}")
            finally:
                self.playwright = None
        logger.debug("CDP 连接已安全释放")
