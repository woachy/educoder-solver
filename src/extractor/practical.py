"""编程实训题提取器 (Practical Extractor).

负责头歌平台编程实训关卡的双栏内容提取与代码靶心分析：
1. 左侧实训任务：通关要求、输入/输出样例、评测说明、相关知识。
2. 右侧在线编辑器：优先探测 Monaco / Ace 实例 API，兜底解析 DOM 文本。
3. 靶心分析 (Target Marker Analysis)：智能识别各类语言注释风格的 Begin-End 区域标记，
   精准切分出 prefix_code (不可变前缀), target_code (待编写区域), suffix_code (不可变后缀)，
   保证拼接无损还原 (prefix_code + target_code + suffix_code == code)。
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag

from src.extractor.base import (
    BaseExtractor,
    PracticalDetails,
    QuestionData,
    QuestionType,
    get_page_html,
)
from src.utils.logger import logger


class PracticalExtractor(BaseExtractor):
    """编程实训题提取器"""

    # 实训左侧任务区域选择器
    LEFT_PANE_SELECTORS = [
        ".shixun-left",
        ".task-description",
        ".task-content",
        "#task-content",
        ".markdown-body",
        ".guide-content",
        ".left-panel",
        ".practical-desc",
        ".subject-content",
    ]

    # 编辑器容器选择器
    EDITOR_CONTAINER_SELECTORS = [
        ".monaco-editor",
        "#monaco-editor",
        ".monaco-container",
        ".ace_editor",
        "#editor",
        ".code-editor",
        ".shixun-editor",
        "textarea.editor-input",
    ]

    # Begin 与 End 区域正则 (适配各类语言风格: //, #, --, /*, <!--, %, REM, 及多星号/井号修饰，兼容 \\xa0 空格)
    BEGIN_PATTERN = re.compile(
        r"^[\s\xa0]*(?://|#|--|/\*|<!--|%|REM)?[\s\xa0*#=\-_~]*\b(BEGIN|START)\b[\s\xa0*#=\-_~]*(?:\*/|-->)?[\s\xa0]*$",
        re.IGNORECASE,
    )
    END_PATTERN = re.compile(
        r"^[\s\xa0]*(?://|#|--|/\*|<!--|%|REM)?[\s\xa0*#=\-_~]*\b(END|STOP)\b[\s\xa0*#=\-_~]*(?:\*/|-->)?[\s\xa0]*$",
        re.IGNORECASE,
    )

    def can_extract(self, page_or_html: Any) -> bool:
        """检查页面是否为编程实训题"""
        try:
            # 1. 如果是支持 evaluate 的页面实例，先探测 Monaco 或 Ace 全局对象
            if hasattr(page_or_html, "evaluate") and callable(page_or_html.evaluate):
                try:
                    has_editor = page_or_html.evaluate(
                        "() => !!((window.monaco && window.monaco.editor) || window.ace || document.querySelector('.monaco-editor'))"
                    )
                    if has_editor:
                        return True
                except Exception:
                    pass

            html = get_page_html(page_or_html)
            soup = BeautifulSoup(html, "html.parser")

            # 2. 检查编辑器特征元素
            for selector in self.EDITOR_CONTAINER_SELECTORS:
                if soup.select(selector):
                    return True

            # 3. 检查特征文字
            text = soup.get_text()
            if any(k in text for k in ["评测", "通关要求", "编程要求", "Begin", "End"]) and any(
                k in text for k in ["代码", "实训", "任务描述", "测试说明"]
            ):
                return True

            return False
        except Exception as e:
            logger.debug(f"PracticalExtractor.can_extract 异常: {e}")
            return False

    def extract(self, page_or_html: Any) -> QuestionData:
        """提取编程实训题完整信息"""
        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")

        # 1. 提取左侧实训任务说明各版块
        left_sections = self._extract_left_pane_sections(soup)

        # 2. 提取代码与编辑器元数据
        code, language, editor_type = self._extract_editor_code(soup, page_or_html)

        # 3. 靶心分析：切分 Begin-End
        prefix_code, target_code, suffix_code, has_marker = self.split_target_code(code)

        # 4. 如果尚未识别语言，从代码特征或文件名推断
        if not language:
            language = self._infer_language(soup, code)

        title = left_sections.get("title") or "编程实训任务"
        desc = left_sections.get("task_description") or ""

        practical_details = PracticalDetails(
            task_description=desc,
            requirements=left_sections.get("requirements", ""),
            sample_io=left_sections.get("sample_io", ""),
            eval_instructions=left_sections.get("eval_instructions", ""),
            code=code,
            prefix_code=prefix_code,
            target_code=target_code,
            suffix_code=suffix_code,
            language=language,
            has_target_marker=has_marker,
            editor_type=editor_type,
        )

        return QuestionData(
            type=QuestionType.PRACTICAL,
            title=title,
            description=desc,
            options=[],
            blanks=[],
            practical_details=practical_details,
            metadata={
                "has_target_marker": has_marker,
                "language": language,
                "editor_type": editor_type,
                "code_length": len(code),
            },
        )

    def _extract_left_pane_sections(self, soup: BeautifulSoup) -> Dict[str, str]:
        """解析左侧面板的各个版块 (任务描述, 编程要求, 测试说明, 评测说明等)"""
        left_node: Optional[Tag] = None
        for selector in self.LEFT_PANE_SELECTORS:
            left_node = soup.select_one(selector)
            if left_node:
                break

        if not left_node:
            left_node = soup.body if soup.body else soup

        # 提取标题
        title = ""
        title_tag = left_node.select_one("h1, h2, h3, .task-title, .title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        sections: Dict[str, List[str]] = {
            "task_description": [],
            "requirements": [],
            "sample_io": [],
            "eval_instructions": [],
        }

        current_section = "task_description"

        # 遍历所有标题和段落提取结构化板块
        elements = left_node.find_all(["h1", "h2", "h3", "h4", "h5", "p", "div", "pre", "ul", "ol"])
        
        for elem in elements:
            # 仅处理直接包含有意义文本且不属于更深层嵌套重复计数的节点
            elem_text = elem.get_text(" ", strip=True)
            if not elem_text:
                continue

            # 检测板块切换
            if any(k in elem_text for k in ["编程要求", "通关要求", "任务要求", "要求"]):
                if elem.name in ["h1", "h2", "h3", "h4", "h5"] or len(elem_text) <= 20:
                    current_section = "requirements"
                    continue
            elif any(k in elem_text for k in ["测试说明", "输入输出样例", "样例说明", "测试样例", "输入格式", "输出格式"]):
                if elem.name in ["h1", "h2", "h3", "h4", "h5"] or len(elem_text) <= 20:
                    current_section = "sample_io"
                    continue
            elif any(k in elem_text for k in ["评测说明", "评测规则", "注意事项"]):
                if elem.name in ["h1", "h2", "h3", "h4", "h5"] or len(elem_text) <= 20:
                    current_section = "eval_instructions"
                    continue
            elif any(k in elem_text for k in ["任务描述", "相关知识", "实训目的"]):
                if elem.name in ["h1", "h2", "h3", "h4", "h5"] or len(elem_text) <= 20:
                    current_section = "task_description"
                    continue

            # 避免将整块大 container 重复加入
            if elem.name in ["p", "pre", "ul", "ol"] or (elem.name == "div" and not elem.find(["p", "div"])):
                sections[current_section].append(elem_text)

        result: Dict[str, str] = {
            "title": title,
            "task_description": "\n\n".join(sections["task_description"]).strip(),
            "requirements": "\n\n".join(sections["requirements"]).strip(),
            "sample_io": "\n\n".join(sections["sample_io"]).strip(),
            "eval_instructions": "\n\n".join(sections["eval_instructions"]).strip(),
        }

        # 如果 task_description 为空，兜底获取整个左侧纯文本
        if not result["task_description"]:
            result["task_description"] = left_node.get_text("\n", strip=True)

        return result

    def _extract_editor_code(self, soup: BeautifulSoup, page_or_html: Any) -> Tuple[str, str, str]:
        """提取编辑器代码内容、语言与编辑器类型"""
        # 1. 优先通过 Playwright 执行 JavaScript 获取编辑器模型内容 (最精准无损)
        if hasattr(page_or_html, "evaluate") and callable(page_or_html.evaluate):
            try:
                js_script = """
                () => {
                    try {
                        if (window.monaco && window.monaco.editor) {
                            const models = window.monaco.editor.getModels();
                            if (models && models.length > 0) {
                                return {
                                    code: models[0].getValue(),
                                    language: models[0].getLanguageId ? models[0].getLanguageId() : "",
                                    editor_type: "monaco"
                                };
                            }
                        }
                        if (window.ace && typeof window.ace.edit === 'function') {
                            const el = document.querySelector('.ace_editor');
                            if (el) {
                                const editor = window.ace.edit(el);
                                return {
                                    code: editor.getValue(),
                                    language: "",
                                    editor_type: "ace"
                                };
                            }
                        }
                    } catch (e) {}
                    return null;
                }
                """
                eval_res = page_or_html.evaluate(js_script)
                if eval_res and isinstance(eval_res, dict) and eval_res.get("code") is not None:
                    return (
                        eval_res.get("code", ""),
                        eval_res.get("language", ""),
                        eval_res.get("editor_type", "monaco"),
                    )
            except Exception as e:
                logger.debug(f"通过 JS 提取编辑器代码失败，转入 DOM 提取: {e}")

        # 2. 从 DOM 中查找 Monaco Editor 渲染的文本行
        view_lines = soup.select(".monaco-editor .view-lines .view-line")
        if view_lines:
            lines = [line.get_text() for line in view_lines]
            return "\n".join(lines), "", "monaco"

        # 3. 从 textarea 或 pre 提取
        textarea = soup.select_one("textarea.editor, textarea#code, textarea.shixun-code, textarea")
        if textarea and textarea.get_text():
            return textarea.get_text(), "", "textarea"
        if textarea and textarea.has_attr("value"):
            return str(textarea["value"]), "", "textarea"

        code_block = soup.select_one(".editor-content, pre.code, code")
        if code_block:
            return code_block.get_text(), "", "dom"

        return "", "", "unknown"

    @classmethod
    def split_target_code(cls, full_code: str) -> Tuple[str, str, str, bool]:
        """靶心切分算法：将完整代码精准拆分为前缀、核心待编写区域与后缀。

        严格满足: prefix_code + target_code + suffix_code == full_code

        Returns:
            Tuple[prefix_code, target_code, suffix_code, has_marker]
        """
        if not full_code:
            return "", "", "", False

        lines = full_code.splitlines(keepends=True)
        begin_line_idx: Optional[int] = None
        end_line_idx: Optional[int] = None

        # 寻找 Begin 标记行
        for idx, line in enumerate(lines):
            line_clean = line.replace('\xa0', ' ').strip()
            if cls.BEGIN_PATTERN.match(line_clean):
                begin_line_idx = idx
                break

        # 如果找到 Begin，继续寻找其后的 End 标记行
        if begin_line_idx is not None:
            for idx in range(begin_line_idx + 1, len(lines)):
                line_clean = lines[idx].replace('\xa0', ' ').strip()
                if cls.END_PATTERN.match(line_clean):
                    end_line_idx = idx
                    break

        if begin_line_idx is not None and end_line_idx is not None:
            # prefix_code: 包含从开头直至 Begin 标记行 (含 Begin 行)
            prefix_code = "".join(lines[: begin_line_idx + 1])
            # target_code: Begin 标记行与 End 标记行之间的纯净待编辑区域
            target_code = "".join(lines[begin_line_idx + 1 : end_line_idx])
            # suffix_code: 从 End 标记行 (含 End 行) 直至文件末尾
            suffix_code = "".join(lines[end_line_idx:])
            return prefix_code, target_code, suffix_code, True

        # 未检测到完整的 Begin-End 标记：整体代码视作待编辑区
        return "", full_code, "", False

    def _infer_language(self, soup: BeautifulSoup, code: str) -> str:
        """从文件名后缀或代码特征推断编程语言"""
        # 1. 尝试从文件选项卡名推断
        file_tab = soup.select_one(".file-tab, .tab-item, .filename, span.file-name")
        if file_tab:
            fname = file_tab.get_text(strip=True).lower()
            ext_map = {
                ".py": "python",
                ".c": "c",
                ".cpp": "cpp",
                ".cc": "cpp",
                ".h": "c",
                ".java": "java",
                ".sql": "sql",
                ".sh": "bash",
                ".go": "go",
                ".js": "javascript",
                ".ts": "typescript",
                ".html": "html",
            }
            for ext, lang in ext_map.items():
                if fname.endswith(ext):
                    return lang

        # 2. 从代码关键词启发式推断
        if "#include" in code or "printf(" in code or "cout <<" in code:
            return "cpp" if "cout <<" in code or "class " in code else "c"
        if "def " in code or "import " in code or "__name__" in code:
            return "python"
        if "public class " in code or "System.out.println" in code:
            return "java"
        if "SELECT " in code.upper() or "INSERT INTO " in code.upper() or "CREATE TABLE" in code.upper():
            return "sql"

        return ""
