"""编程实训题代码安全注入器 (Code Editor Action Executor).

负责头歌实训关卡在线代码编辑器的安全修改与内容注入：
1. 自动快照备份：修改代码前，自动读取编辑器当前已有内容，持久化保存至 .cache/backups/backup_<timestamp>.py。
2. 靶心组装保护 (Target Assembly)：若 target_only=True 且存在 Begin-End 区域，
   自动与不可变的前缀骨架 (prefix_code) 和后缀骨架 (suffix_code) 组装，严防破坏评测测试引导代码。
3. 分级安全注入规范：
   - 优先级 1: page.evaluate() 调用 Monaco 内部 API (monaco.editor.getModels()[0].setValue(val))。
   - 优先级 2: Ace Editor 内部 API (ace.edit().setValue(val))。
   - 兜底方案: 聚焦编辑器 -> Control+A 全选 -> Backspace 清空 -> 键入注入。严禁直接 innerHTML 破坏 DOM 挂载。
4. 结构化回执：返回包含备份文件路径、注入方式、组装后完整代码的操作结果。
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from playwright.sync_api import Page

from src.extractor.base import PracticalDetails, QuestionData, QuestionType
from src.extractor.detector import extract_question
from src.extractor.practical import PracticalExtractor
from src.utils.delay import random_delay
from src.utils.logger import logger


# 项目根目录与备份目录解析
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKUP_DIR = PROJECT_ROOT / ".cache" / "backups"


def _ensure_backup_dir() -> Path:
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def backup_code_to_file(code_content: str, lang: str = "py") -> str:
    """将代码内容保存至备份目录。

    Args:
        code_content: 待备份的代码文本
        lang: 文件扩展名后缀

    Returns:
        str: 备份文件的绝对路径
    """
    _ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    # 确保内容为字符串类型
    if not isinstance(code_content, str):
        code_content = str(code_content or "")

    # 语言映射对应扩展名
    ext_map = {
        "python": "py",
        "c": "c",
        "cpp": "cpp",
        "java": "java",
        "sql": "sql",
        "javascript": "js",
        "bash": "sh",
    }
    ext = ext_map.get(lang.lower(), lang.lower()) if lang else "py"
    if not ext.startswith("."):
        ext = f".{ext}"

    filename = f"backup_{timestamp}{ext}"
    target_path = BACKUP_DIR / filename

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(code_content)
        abs_path = str(target_path.resolve())
        logger.info(f"已创建原代码快照备份: {abs_path}")
        return abs_path
    except Exception as e:
        logger.error(f"代码备份失败: {e}")
        return ""


def _get_all_frames(page: Any) -> list:
    """获取页面主实例及所有子 iframe 实例列表。"""
    frames = [page]
    # 仅当 page.frames 为真实的列表或元组容器时遍历子 frame，兼容单元测试 Mock
    if hasattr(page, "frames") and isinstance(page.frames, (list, tuple)):
        for f in page.frames:
            if f != page and f not in frames:
                frames.append(f)
    return frames


def get_current_editor_code(page: Page) -> str:
    """读取当前编辑器中的已有代码文本（支持跨 iframe 与 React/Vue Fiber 探查）。"""
    frames = _get_all_frames(page)

    # 1. 优先遍历所有 frames 通过 Monaco / Ace JS API 或 Fiber 对象获取
    detect_js = """
    () => {
        try {
            // 1. 全局 window.monaco || window.Monaco
            const m = window.monaco || window.Monaco;
            if (m && m.editor) {
                const models = m.editor.getModels();
                if (models && models.length > 0) return models[0].getValue();
            }
            // 2. React / Vue Fiber 挂载探查
            const editorEls = document.querySelectorAll('.monaco-editor, .my-monaco-editor');
            for (const el of editorEls) {
                const fiberKey = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                if (fiberKey) {
                    let curr = el[fiberKey];
                    while (curr) {
                        const props = curr.memoizedProps || {};
                        const state = curr.memoizedState || {};
                        const ed = props.monacoEditor || props.editor || state.monacoEditor || state.editor;
                        if (ed && typeof ed.getValue === 'function') {
                            return ed.getValue();
                        }
                        if (ed && typeof ed.getModel === 'function' && ed.getModel()) {
                            return ed.getModel().getValue();
                        }
                        curr = curr.return;
                    }
                }
                if (el.__vue__ && el.__vue__.editor && typeof el.__vue__.editor.getValue === 'function') {
                    return el.__vue__.editor.getValue();
                }
            }
            // 3. Ace Editor
            if (window.ace && typeof window.ace.edit === 'function') {
                const el = document.querySelector('.ace_editor');
                if (el) return window.ace.edit(el).getValue();
            }
        } catch (e) {}
        return null;
    }
    """

    for f in frames:
        if hasattr(f, "evaluate") and callable(f.evaluate):
            try:
                code = f.evaluate(detect_js)
                if code is not None and isinstance(code, str):
                    return code
            except Exception as e:
                logger.debug(f"Frame 读取当前代码失败: {e}")

    # 2. 兜底从 textarea 或 DOM 文本提取
    try:
        ta = page.query_selector("textarea.editor, textarea#code, textarea")
        if ta:
            val = ta.input_value()
            if val and isinstance(val, str):
                return val
    except Exception:
        pass

    try:
        view_lines = page.query_selector_all(
            ".monaco-editor .view-lines .view-line, .my-monaco-editor .view-lines .view-line"
        )
        if not view_lines:
            view_lines = page.query_selector_all(".view-lines .view-line")
        if view_lines:
            lines = [l.inner_text() for l in view_lines]
            return "\n".join(lines)
    except Exception:
        pass

    return ""


def assemble_target_code(
    new_code: str,
    prefix_code: str,
    suffix_code: str,
    has_marker: bool,
) -> Tuple[str, bool]:
    """靶心代码组装算法。

    当检测到 Begin-End 区域时，将用户编写的纯净核心逻辑安全包裹在不可变测试骨架中。

    Args:
        new_code: 用户或 Agent 编写的新代码
        prefix_code: Begin 标记及之前的骨架
        suffix_code: End 标记及之后的骨架
        has_marker: 是否存在有效标记

    Returns:
        Tuple[str, bool]: (组装后的完整代码, 是否执行了靶心组装)
    """
    if not has_marker or (not prefix_code and not suffix_code):
        return new_code, False

    # 规范换行
    body = new_code
    if not body.endswith("\n"):
        body = body + "\n"

    # 若 new_code 已包含了 Begin/End 标记，则不进行二次嵌套包裹
    if "Begin" in new_code and "End" in new_code:
        return new_code, False

    full_code = prefix_code + body + suffix_code
    return full_code, True


def inject_code(
    page: Page,
    new_code: str,
    target_only: bool = True,
    question_data: Optional[QuestionData] = None,
) -> Dict[str, Any]:
    """向头歌实训在线编辑器安全注入新代码。

    遵循 AGENTS.md 规范：
    1. 前置自动备份已有代码至 .cache/backups/。
    2. target_only 保护模式下，若存在 Begin-End 区域则无损拼接外围骨架。
    3. 严格遵循 Monaco API 优先 -> Ace API -> 键盘选中覆盖的注入分级，严禁 innerHTML。

    Args:
        page: Playwright Page 实例
        new_code: 待注入的代码字符串
        target_only: 是否仅替换 Begin-End 之间的靶心区域（默认为 True）
        question_data: 可选的预提取实训题数据模型

    Returns:
        dict: 操作回执字典:
            - success (bool): 注入是否成功
            - backup_path (str): 备份文件路径
            - method_used (str): 使用的注入方法 ('monaco_api', 'ace_api', 'keyboard_fallback', 'textarea_value')
            - full_code (str): 最终注入到编辑器的完整代码
            - is_target_assembled (bool): 是否进行了靶心拼接
            - saved (bool): 是否已触发保存 (onSave 或 Control+S 兜底)
            - commit_id (str): 若成功触发 onSave 提取到的后端 Git Commit ID
            - message (str): 操作说明
    """
    if new_code is None:
        return {
            "success": False,
            "backup_path": "",
            "method_used": "none",
            "full_code": "",
            "target_only": target_only,
            "is_target_assembled": False,
            "fallback_to_full": False,
            "saved": False,
            "commit_id": "",
            "message": "待注入代码不能为空",
        }

    # 1. 读取编辑器当前代码
    current_code = get_current_editor_code(page)
    if not current_code and question_data and question_data.practical_details:
        current_code = question_data.practical_details.code

    # 推断语言以确定备份文件扩展名
    lang = "py"
    if question_data and question_data.practical_details and question_data.practical_details.language:
        lang = question_data.practical_details.language

    # 2. 执行安全备份
    backup_path = backup_code_to_file(current_code, lang=lang)

    # 3. 靶心代码组装判定
    full_code = new_code
    is_assembled = False
    fallback_to_full = False

    if target_only:
        # 尝试从 question_data 获取切分信息，或基于当前代码动态切分
        prefix_code = ""
        suffix_code = ""
        has_marker = False

        if question_data and question_data.practical_details and question_data.practical_details.has_target_marker:
            prefix_code = question_data.practical_details.prefix_code
            suffix_code = question_data.practical_details.suffix_code
            has_marker = True
        elif current_code:
            prefix_code, _, suffix_code, has_marker = PracticalExtractor.split_target_code(current_code)

        if has_marker:
            full_code, is_assembled = assemble_target_code(new_code, prefix_code, suffix_code, has_marker)
            logger.info("已成功将新代码安全组装至 Begin-End 靶心区域")
        else:
            fallback_to_full = True
            logger.info("未检测到 Begin-End 靶心标记，将自动降级执行完整代码写入 (fallback_to_full)")

    # 4. 执行分级安全注入
    method_used = "none"
    success = False
    saved = False
    commit_id = ""

    # 级别 1: Monaco Editor 原生 API & Fiber 深度穿透 (跨所有 frames)
    frames = _get_all_frames(page)
    monaco_js = """
    async (val) => {
        try {
            // 1. React / Vue Fiber 挂载探查
            const editorEls = document.querySelectorAll('.monaco-editor, .my-monaco-editor');
            for (const el of editorEls) {
                const fiberKey = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                if (fiberKey) {
                    let curr = el[fiberKey];
                    while (curr) {
                        const props = curr.memoizedProps || {};
                        const state = curr.memoizedState || {};
                        const ed = props.monacoEditor || props.editor || state.monacoEditor || state.editor;
                        if (ed) {
                            let injected = false;
                            if (typeof ed.setValue === 'function') {
                                ed.setValue(val);
                                injected = true;
                            } else if (typeof ed.getModel === 'function' && ed.getModel()) {
                                ed.getModel().setValue(val);
                                injected = true;
                            } else if (ed.editor && typeof ed.editor.setValue === 'function') {
                                ed.editor.setValue(val);
                                injected = true;
                            }

                            // 兜底结合全局 Monaco 实例赋值
                            if (!injected) {
                                const m = window.monaco || window.Monaco;
                                if (m && m.editor) {
                                    const models = m.editor.getModels();
                                    if (models && models.length > 0) {
                                        models[0].setValue(val);
                                        injected = true;
                                    }
                                }
                            }

                            // 显式调用 onChange(val) 通知 React 组件状态更新
                            if (typeof ed.onChange === 'function') {
                                try { ed.onChange(val); } catch (e) {}
                            } else if (typeof props.onChange === 'function') {
                                try { props.onChange(val); } catch (e) {}
                            }

                            // 显式调用 onSave(1) 触发向后端提交 Git Commit
                            let hasSaved = false;
                            let cid = "";
                            let saveRes = null;
                            if (typeof ed.onSave === 'function') {
                                try {
                                    saveRes = ed.onSave(1);
                                    hasSaved = true;
                                } catch (e) {}
                            } else if (typeof props.onSave === 'function') {
                                try {
                                    saveRes = props.onSave(1);
                                    hasSaved = true;
                                } catch (e) {}
                            }

                            if (saveRes && typeof saveRes.then === 'function') {
                                try { saveRes = await saveRes; } catch (e) {}
                            }
                            if (saveRes && typeof saveRes === 'object') {
                                cid = saveRes.commitID || saveRes.commit_id ||
                                      (saveRes.data && (saveRes.data.commitID || saveRes.data.commit_id)) || "";
                            }
                            if (!cid) {
                                cid = ed.commitID || ed.commit_id || props.commitID || props.commit_id || "";
                            }

                            if (injected) {
                                return {
                                    injected: true,
                                    saved: hasSaved,
                                    commit_id: cid ? String(cid) : ""
                                };
                            }
                        }
                        curr = curr.return;
                    }
                }
                if (el.__vue__ && el.__vue__.editor && typeof el.__vue__.editor.setValue === 'function') {
                    el.__vue__.editor.setValue(val);
                    return { injected: true, saved: false, commit_id: "" };
                }
            }

            // 2. 全局 window.monaco || window.Monaco 实例
            const m = window.monaco || window.Monaco;
            if (m && m.editor) {
                const models = m.editor.getModels();
                if (models && models.length > 0) {
                    models[0].setValue(val);
                    return { injected: true, saved: false, commit_id: "" };
                }
            }
        } catch (e) {}
        return false;
    }
    """
    for f in frames:
        if hasattr(f, "evaluate") and callable(f.evaluate):
            try:
                injected_res = f.evaluate(monaco_js, full_code)
                if isinstance(injected_res, dict) and injected_res.get("injected"):
                    method_used = "monaco_api"
                    success = True
                    saved = bool(injected_res.get("saved", False))
                    commit_id = str(injected_res.get("commit_id") or "")
                    logger.success(
                        f"通过 Monaco 原生/Fiber 内存 API 成功注入代码 (saved: {saved}, commit_id: {commit_id})"
                    )
                    break
                elif injected_res is True:
                    method_used = "monaco_api"
                    success = True
                    logger.success("通过 Monaco 原生 API 成功注入代码")
                    break
            except Exception as e:
                logger.debug(f"Frame Monaco API 注入异常: {e}")

    # 级别 2: Ace Editor 原生 API (跨所有 frames)
    if not success:
        ace_js = """
        (val) => {
            try {
                if (window.ace && typeof window.ace.edit === 'function') {
                    const el = document.querySelector('.ace_editor');
                    if (el) {
                        const ed = window.ace.edit(el);
                        ed.setValue(val, -1);
                        return true;
                    }
                }
            } catch (e) {}
            return false;
        }
        """
        for f in frames:
            if hasattr(f, "evaluate") and callable(f.evaluate):
                try:
                    injected = f.evaluate(ace_js, full_code)
                    if injected:
                        method_used = "ace_api"
                        success = True
                        logger.success("通过 Ace 原生 API (setValue) 成功注入代码")
                        break
                except Exception as e:
                    logger.debug(f"Frame Ace API 注入异常: {e}")

    # 级别 3: 兜底方案 (聚焦 -> 全选 -> 清空 -> 键入/粘贴)
    if not success:
        try:
            logger.info("正在执行键盘模拟全选覆盖兜底方案...")
            editor_selectors = [
                ".monaco-editor",
                ".my-monaco-editor",
                ".ace_editor",
                ".code-editor",
                "textarea.editor",
                "#monaco-editor",
            ]
            clicked = False
            for sel in editor_selectors:
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click()
                        clicked = True
                        break
                except Exception:
                    continue

            random_delay(0.1, 0.2)
            if hasattr(page, "keyboard"):
                page.keyboard.press("Control+A")
                random_delay(0.05, 0.1)
                page.keyboard.press("Backspace")
                random_delay(0.05, 0.1)

                if hasattr(page.keyboard, "insert_text"):
                    page.keyboard.insert_text(full_code)
                elif hasattr(page.keyboard, "type"):
                    page.keyboard.type(full_code)

                method_used = "keyboard_fallback"
                success = True
                logger.success("通过键盘模拟覆盖成功注入代码")
        except Exception as e:
            logger.error(f"键盘覆盖兜底方案失败: {e}")

    # 级别 4: Textarea DOM 兜底
    if not success and hasattr(page, "evaluate") and callable(page.evaluate):
        try:
            ta_js = """
            (val) => {
                const ta = document.querySelector('textarea.editor, textarea#code, textarea');
                if (ta) {
                    ta.value = val;
                    ta.dispatchEvent(new Event('input', { bubbles: true }));
                    ta.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
                return false;
            }
            """
            injected = page.evaluate(ta_js, full_code)
            if injected:
                method_used = "textarea_value"
                success = True
                logger.success("通过 Textarea 赋值成功注入代码")
        except Exception as e:
            logger.debug(f"Textarea 赋值异常: {e}")

    # 5. 若未触发 onSave（例如纯 Monaco 模式），兜底使用 Control+S 并微延迟保存
    if success and not saved:
        try:
            if hasattr(page, "keyboard") and hasattr(page.keyboard, "press"):
                logger.info("未触发 onSave，执行 Control+S 键盘快捷键兜底保存...")
                page.keyboard.press("Control+S")
                random_delay(0.2, 0.5)
                saved = True
                logger.success("已通过 Control+S 兜底触发保存")
        except Exception as se:
            logger.debug(f"快捷键兜底保存异常: {se}")

    result = {
        "success": success,
        "backup_path": backup_path,
        "method_used": method_used,
        "full_code": full_code,
        "target_only": target_only,
        "is_target_assembled": is_assembled,
        "fallback_to_full": fallback_to_full,
        "saved": saved,
        "commit_id": commit_id,
        "message": (
            f"代码安全注入成功 (方法: {method_used}, 保存: {saved}, commit_id: {commit_id}, 备份: {backup_path})"
            if success
            else f"代码注入失败，但原代码已安全备份至 {backup_path}"
        ),
    }

    return result
