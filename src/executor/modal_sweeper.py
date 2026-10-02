"""弹窗与遮罩清理器 (Modal & Blocking Overlay Sweeper).

负责在代码注入或评测交互前，自动识别并清理可能遮挡操作或拦截鼠标事件的各类弹窗与遮罩：
1. 通关庆祝/金币经验弹窗 (.evaluate-result-container, 继续挑战等)。
2. Ant Design / Element UI 模态对话框 (.ant-modal-close, .el-dialog__close)。
3. 拦截鼠标指针事件 (intercepts pointer events) 的残留遮罩层。
"""

import time
from typing import Any, List, Set
from playwright.sync_api import ElementHandle, Page

from src.utils.logger import logger


# 常见弹窗关闭按钮选择器
MODAL_CLOSE_SELECTORS: List[str] = [
    ".ant-modal-close",
    ".ant-modal-close-x",
    "button[aria-label='Close']",
    "button[aria-label='close']",
    ".el-dialog__headerbtn",
    ".el-message-box__headerbtn",
    ".evaluate-result-container .close-btn",
    ".evaluate-result-container .close",
    ".evaluate-result-container i.iconfont",
    "button:has-text('我知道了')",
    "button:has-text('继续挑战')",
    "button:has-text('关闭')",
    ".shixun-modal-close",
    ".modal .close",
]


def dismiss_blocking_overlays(page: Page) -> int:
    """自动识别并清理页面上的遮挡弹窗与拦截指针事件的遮罩层。

    Args:
        page: Playwright Page 实例

    Returns:
        int: 被关闭或清理的弹窗/遮罩数量
    """
    dismissed_count = 0

    if not page:
        return 0

    clicked_elements: Set[Any] = set()

    # 1. 尝试定位并点击常见的弹窗关闭按钮
    for selector in MODAL_CLOSE_SELECTORS:
        try:
            if hasattr(page, "query_selector_all"):
                elements = page.query_selector_all(selector)
                for el in elements:
                    try:
                        # 避免同一元素在不同选择器中被重复点击计数
                        if el in clicked_elements:
                            continue
                        if hasattr(el, "is_visible") and el.is_visible():
                            el.click()
                            clicked_elements.add(el)
                            dismissed_count += 1
                            logger.info(f"已清理遮挡弹窗 (选择器: {selector})")
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. 检查并清理拦截鼠标事件的残留遮罩层 (Pointer-blocking masks)
    if hasattr(page, "evaluate") and callable(page.evaluate):
        try:
            js_script = """
            () => {
                let count = 0;
                // 常见遮罩层选择器
                const maskSelectors = [
                    '.ant-modal-mask',
                    '.ant-modal-wrap',
                    '.modal-backdrop',
                    '.v-modal',
                    '.shixun-modal-mask',
                    '.ant-spin-nested-loading > div > .ant-spin-spinning',
                ];

                maskSelectors.forEach(sel => {
                    try {
                        const masks = document.querySelectorAll(sel);
                        masks.forEach(m => {
                            const style = window.getComputedStyle(m);
                            // 若遮罩显示且可能阻断指针交互
                            if (style.display !== 'none' && style.visibility !== 'hidden') {
                                const hasVisibleModal = m.querySelector('.ant-modal, .el-dialog, .modal-content');
                                // 若无可见内容或透明度极低，视为残留死锁遮罩，安全将其取消指针拦截
                                if (!hasVisibleModal || style.opacity === '0') {
                                    m.style.pointerEvents = 'none';
                                    m.style.display = 'none';
                                    count++;
                                }
                            }
                        });
                    } catch (e) {}
                });
                return count;
            }
            """
            js_cleaned = page.evaluate(js_script)
            if isinstance(js_cleaned, int) and js_cleaned > 0:
                dismissed_count += js_cleaned
                logger.info(f"通过 JS 清理了 {js_cleaned} 个拦截鼠标指针事件的残留遮罩层")
        except Exception as e:
            logger.debug(f"清理残留遮罩脚本执行异常: {e}")

    return dismissed_count
