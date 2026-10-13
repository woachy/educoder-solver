"""CDP 浏览器管理器与探活单元测试 (Browser Manager Tests).

验证:
1. 端口前置探活 (可用与离线状态判定)
2. CDP 离线优雅容错与明确提示
3. 标签页智能检索与容错回退机制
4. 安全断开机制 (确保不关闭物理浏览器与用户页面)
"""

import socket
import threading
from unittest.mock import MagicMock, call, patch
import pytest

from src.browser.manager import (
    BrowserSession,
    TargetPageNotFoundError,
    check_cdp_available,
)


def _start_dummy_server():
    """在随机空闲端口启动一个临时的 TCP 监听服务用于测试探活"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    
    stop_event = threading.Event()

    def run():
        sock.settimeout(0.5)
        while not stop_event.is_set():
            try:
                conn, _ = sock.accept()
                conn.close()
            except (socket.timeout, OSError):
                pass
        sock.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return port, stop_event, sock


class TestCheckCdpAvailable:
    """测试 CDP 端口网络探活"""

    def test_cdp_available_when_listening(self):
        """测试端口开放时返回 True"""
        port, stop_event, _ = _start_dummy_server()
        try:
            assert check_cdp_available("127.0.0.1", port=port, timeout=1.0) is True
        finally:
            stop_event.set()

    def test_cdp_unavailable_when_closed(self):
        """测试端口关闭时安全返回 False 而不崩溃"""
        # 使用未监听的高位端口
        assert check_cdp_available("127.0.0.1", port=59123, timeout=0.2) is False


class TestBrowserSession:
    """测试 BrowserSession 上下文管理器与页面检索逻辑"""

    def test_session_offline_raises_connection_error(self):
        """当 CDP 端口未开启时，应立即中断并提示友好的启动脚本路径"""
        with pytest.raises(ConnectionError) as exc_info:
            with BrowserSession(port=59124, timeout=0.2):
                pass

        err_msg = str(exc_info.value)
        assert "59124" in err_msg
        assert "launch_browser.ps1" in err_msg
        assert "--remote-debugging-port" in err_msg

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.time.sleep")
    @patch("src.browser.manager.sync_playwright")
    def test_session_retry_connect_success(self, mock_playwright_cm, mock_sleep, mock_check_cdp):
        """测试首轮 connect_over_cdp 抛异常、第二轮重试成功的自愈场景"""
        mock_browser = MagicMock()
        mock_playwright = MagicMock()
        # 首轮抛异常，第二轮返回 mock_browser
        mock_playwright.chromium.connect_over_cdp.side_effect = [
            RuntimeError("Connection refused by CDP endpoint"),
            mock_browser,
        ]
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222, max_retries=3, retry_delay=1.0) as session:
            assert session.browser == mock_browser

        # 验证调用了 2 次 connect_over_cdp
        assert mock_playwright.chromium.connect_over_cdp.call_count == 2
        # 验证触发了 1 次退避等待，间隔为 retry_delay * 1 = 1.0s
        mock_sleep.assert_called_once_with(1.0)

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.time.sleep")
    @patch("src.browser.manager.sync_playwright")
    def test_session_retry_exceeded_raises_connection_error(self, mock_playwright_cm, mock_sleep, mock_check_cdp):
        """测试重试超过 max_retries 后正确抛出 ConnectionError 并清理资源"""
        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.side_effect = RuntimeError("CDP socket closed")
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        session = BrowserSession(port=9222, max_retries=3, retry_delay=0.5)
        with pytest.raises(ConnectionError) as exc_info:
            with session:
                pass

        err_msg = str(exc_info.value)
        assert "连接 CDP 失败" in err_msg
        assert "3" in err_msg
        assert "launch_browser.ps1" in err_msg
        assert "--remote-debugging-port" in err_msg

        # 验证尝试了 3 次
        assert mock_playwright.chromium.connect_over_cdp.call_count == 3
        # 验证前两次失败进行了退避重试: 0.5 * 1 = 0.5s, 0.5 * 2 = 1.0s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(0.5), call(1.0)])
        # 验证资源被清理: playwright.stop() 已被调用，实例引用被释放
        mock_playwright.stop.assert_called_once()
        assert session.playwright is None
        assert session.browser is None

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.sync_playwright")
    def test_session_get_target_page_by_url(self, mock_playwright_cm, mock_check_cdp):
        """优先根据 URL 匹配目标头歌标签页"""
        # 构造 Mock 页面
        mock_page_other = MagicMock()
        mock_page_other.url = "https://www.baidu.com"
        mock_page_other.title.return_value = "百度一下"

        mock_page_touge = MagicMock()
        mock_page_touge.url = "https://www.educoder.net/tasks/abc123"
        mock_page_touge.title.return_value = "实训作业 - 头歌教学平台"

        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page_other, mock_page_touge]
        mock_browser.contexts = [mock_context]

        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222) as session:
            target_page = session.get_target_page("educoder.net")
            assert target_page == mock_page_touge
            assert "educoder.net" in target_page.url

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.sync_playwright")
    def test_session_get_target_page_by_title(self, mock_playwright_cm, mock_check_cdp):
        """当 URL 未显式包含关键字时，根据页面 Title 匹配"""
        mock_page = MagicMock()
        mock_page.url = "http://internal-domain.org/app"
        mock_page.title.return_value = "头歌实践教学平台 - 关卡评测"

        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_browser.contexts = [mock_context]

        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222) as session:
            target_page = session.get_target_page("头歌")
            assert target_page == mock_page

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.sync_playwright")
    def test_session_target_page_fallback(self, mock_playwright_cm, mock_check_cdp):
        """未找到关键字但存在其它标签页时，容错回退使用第一个标签页"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.title.return_value = "Example Page"

        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_browser.contexts = [mock_context]

        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222) as session:
            # 开启容错回退
            page = session.get_target_page("educoder.net", fallback_first=True)
            assert page == mock_page

            # 关闭容错回退应抛出异常
            with pytest.raises(TargetPageNotFoundError) as exc_info:
                session.get_target_page("educoder.net", fallback_first=False)
            assert "未找到包含 'educoder.net' 的标签页" in str(exc_info.value)

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.sync_playwright")
    def test_session_safe_exit_preserves_pages(self, mock_playwright_cm, mock_check_cdp):
        """验证退出上下文时，仅释放 CDP 连接，严禁关闭任何页面或上下文"""
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_context]

        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222) as session:
            assert session.browser is not None

        # 校验：CDP 连接已断开，playwright 停止
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

        # 绝对红线：页面与 context 绝不能调用 close()
        mock_page.close.assert_not_called()
        mock_context.close.assert_not_called()
