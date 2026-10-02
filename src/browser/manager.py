"""CDP 浏览器管理器 (Browser Manager).

负责与用户物理浏览器 (Chrome / Edge) 的 Chrome DevTools Protocol (CDP) 调试端口建立挂载，
提供端口前置探活、标签页智能捕获、会话生命周期管理与安全断开。
严格遵守 AGENTS.md 规范：
1. 任何操作前必须前置探活 localhost:9222。
2. 断开连接时严禁关闭用户物理浏览器或用户已有页面。
"""

import socket
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
    ):
        self.host = host or config.browser.host
        self.port = port or config.browser.port
        self.timeout = timeout
        self.connect_timeout_ms = connect_timeout_ms or config.browser.connect_timeout_ms
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
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(
                self.cdp_url,
                timeout=self.connect_timeout_ms,
            )
            logger.success(f"已成功通过 CDP 挂载物理浏览器会话")
        except Exception as e:
            self.__exit__(None, None, None)
            raise ConnectionError(f"连接 CDP 失败: {str(e)}") from e

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

    def get_target_page(self, url_keyword: str = "educoder.net", fallback_first: bool = True) -> Page:
        """优先定位包含指定关键字的目标标签页。

        Args:
            url_keyword: 匹配的 URL 或标题关键字，默认 'educoder.net'
            fallback_first: 若未找到匹配标签页，是否容错回退至第一个可用标签页

        Returns:
            Page: 目标页面实例

        Raises:
            TargetPageNotFoundError: 未找到匹配标签页且无法回退时抛出
        """
        current_pages = self.pages
        if not current_pages:
            raise TargetPageNotFoundError("当前浏览器中未检测到任何已打开的标签页。")

        # 1. 最优先匹配具体的实训/任务关卡页面 (/tasks/ 或 /shixuns/)
        for page in current_pages:
            try:
                u = page.url.lower()
                if url_keyword.lower() in u and ("/tasks/" in u or "/shixuns/" in u):
                    logger.info(f"已精准匹配实训任务页面: [{page.title()}]({page.url})")
                    return page
            except Exception:
                continue

        # 2. 其次按 URL 包含关键字匹配
        for page in current_pages:
            try:
                if url_keyword.lower() in page.url.lower():
                    logger.info(f"已匹配目标页面 (URL匹配): [{page.title()}]({page.url})")
                    return page
            except Exception:
                continue

        # 其次按标题包含关键字匹配
        for page in current_pages:
            try:
                if url_keyword.lower() in page.title().lower():
                    logger.info(f"已匹配目标页面 (标题匹配): [{page.title()}]({page.url})")
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
