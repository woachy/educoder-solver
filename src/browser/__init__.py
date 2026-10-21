"""CDP 浏览器控制与生命周期管理模块"""

from src.browser.manager import (
    BrowserSession,
    TargetPageNotFoundError,
    check_cdp_available,
    is_classroom_page,
    is_shixun_task_page,
    is_springboard_page,
)

__all__ = [
    "BrowserSession",
    "TargetPageNotFoundError",
    "check_cdp_available",
    "is_classroom_page",
    "is_springboard_page",
    "is_shixun_task_page",
]
