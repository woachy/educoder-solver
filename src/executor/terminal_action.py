"""Web 终端 xterm.js 接管与命令注入执行器 (Terminal Action Executor).

负责头歌平台实训关卡 Web 终端 (xterm.js) 的命令注入与输出监听：
1. 采用 DataTransfer + ClipboardEvent('paste') 向 .xterm-helper-textarea 或 .xterm-screen
   派发粘贴事件注入命令文本，杜绝键盘模拟丢字符与空格丢失问题。
2. 支持 execute_enter 控制命令末尾追加换行执行。
3. 提供 read_terminal_output 提取 .xterm-rows 可见文本行。
4. 全程异常捕获与平滑回退，提供规范化 logger 日志输出。
"""

from typing import Any, List, Optional
from playwright.sync_api import Page

from src.utils.logger import logger


def _get_all_frames(page: Any) -> List[Any]:
    """获取 page 及其所有子 frame，安全兼容单元测试中的 Mock 对象。"""
    frames = [page]
    if hasattr(page, "frames") and isinstance(page.frames, (list, tuple)):
        for f in page.frames:
            if f != page and f not in frames:
                frames.append(f)
    return frames


def inject_terminal_command(
    page: Page,
    command: str,
    execute_enter: bool = True,
) -> bool:
    """向页面中的 xterm.js Web 终端注入命令文本。

    采用 DataTransfer + ClipboardEvent('paste') 向 .xterm-helper-textarea 或 .xterm-screen
    派发粘贴事件注入命令文本，杜绝键盘模拟丢字符/空格丢失问题。

    Args:
        page: Playwright Page 页面实例
        command: 要注入的命令字符串
        execute_enter: 是否在命令末尾添加换行并执行（默认为 True）

    Returns:
        bool: 注入成功返回 True；若页面中找不到终端 textarea 或注入失败则返回 False
    """
    if not page:
        logger.warning("传入的 page 对象为空，无法注入终端命令")
        return False

    try:
        # 1. 规范化命令内容
        text_to_paste = command if command is not None else ""
        if execute_enter and not text_to_paste.endswith("\n"):
            text_to_paste += "\n"

        cmd_display = command.strip() if command else ""
        logger.info(f"准备向 Web 终端注入命令: {cmd_display!r} (execute_enter={execute_enter})")

        frames = _get_all_frames(page)

        # 2. 前置探查终端元素（若环境支持 query_selector）
        target_found = True
        if hasattr(page, "query_selector") and callable(page.query_selector):
            try:
                el = page.query_selector(".xterm-helper-textarea") or page.query_selector(".xterm-screen")
                if el is None:
                    # 检查是否有其它 frame 存在终端元素
                    has_frame_el = False
                    for f in frames[1:]:
                        if hasattr(f, "query_selector") and callable(f.query_selector):
                            f_el = f.query_selector(".xterm-helper-textarea") or f.query_selector(".xterm-screen")
                            if f_el is not None:
                                has_frame_el = True
                                break
                    if not has_frame_el:
                        target_found = False
            except Exception as e:
                logger.debug(f"query_selector 探查终端元素异常: {e}")

        if not target_found:
            logger.warning("页面中未找到对应终端 textarea 或 screen 元素 (.xterm-helper-textarea / .xterm-screen)")
            return False

        # 3. 构造注入脚本：通过 DataTransfer + ClipboardEvent('paste') 派发事件
        inject_js = """
        (args) => {
            try {
                const text = args.text;
                const el = document.querySelector('.xterm-helper-textarea') || document.querySelector('.xterm-screen');
                if (!el) {
                    return false;
                }
                if (typeof el.focus === 'function') {
                    el.focus();
                }
                const dt = new DataTransfer();
                dt.setData('text/plain', text);
                const pasteEvent = new ClipboardEvent('paste', {
                    clipboardData: dt,
                    bubbles: true,
                    cancelable: true,
                    composed: true,
                });
                el.dispatchEvent(pasteEvent);
                return true;
            } catch (err) {
                return false;
            }
        }
        """

        injected = False
        for f in frames:
            if hasattr(f, "evaluate") and callable(f.evaluate):
                try:
                    res = f.evaluate(inject_js, {"text": text_to_paste})
                    if res is True or (isinstance(res, dict) and res.get("success")):
                        injected = True
                        break
                    elif res is False:
                        continue
                except Exception as e:
                    logger.debug(f"Frame evaluate 注入终端命令异常: {e}")

        if injected:
            logger.info("成功通过 ClipboardEvent 粘贴注入终端命令")
            return True
        else:
            logger.warning("未检测到 xterm.js 终端元素 (.xterm-helper-textarea 或 .xterm-screen)，命令注入失败")
            return False

    except Exception as e:
        logger.error(f"注入终端命令发生未捕获异常: {e}")
        return False


def read_terminal_output(page: Page) -> str:
    """提取当前 Web 终端屏幕中可见的文本内容。

    通过 evaluate 提取 .xterm-rows 中的文本行，保留换行。
    若页面中未找到终端行元素或发生异常，则平滑返回空字符串。

    Args:
        page: Playwright Page 页面实例

    Returns:
        str: 终端可见文本内容（保留换行），未找到或异常时返回空字符串 ""
    """
    if not page:
        return ""

    read_js = """
    () => {
        try {
            const rowsContainer = document.querySelector('.xterm-rows');
            if (!rowsContainer) {
                return null;
            }
            const children = rowsContainer.children;
            if (children && children.length > 0) {
                const lines = [];
                for (let i = 0; i < children.length; i++) {
                    lines.push(children[i].textContent || "");
                }
                return lines.join("\\n");
            }
            return rowsContainer.textContent || "";
        } catch (e) {
            return null;
        }
    }
    """

    try:
        frames = _get_all_frames(page)
        for f in frames:
            if hasattr(f, "evaluate") and callable(f.evaluate):
                try:
                    res = f.evaluate(read_js)
                    if res is not None and isinstance(res, str):
                        return res
                except Exception as e:
                    logger.debug(f"Frame 读取终端输出异常: {e}")
    except Exception as e:
        logger.error(f"读取终端输出发生未捕获异常: {e}")

    return ""
