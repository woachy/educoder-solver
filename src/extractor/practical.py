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

    # Begin 与 End 区域正则 (适配各类语言风格: //, #, --, /*, <!--, %, REM, 及多星号/井号修饰，兼容 \xa0 空格，兼容各类中文注释风格)
    BEGIN_PATTERN = re.compile(
        r"^[\s\xa0]*(?://|#|--|/\*|<!--|%|REM)?[\s\xa0*#=\-_~]*(?:\b(?:BEGIN|START)\b|代码开始|开始编写(?:你的)?代码|开始(?:答题|编写|作答)?|在此处编写代码)[\s\xa0*#=\-_~]*(?:\*/|-->)?[\s\xa0]*$",
        re.IGNORECASE,
    )
    END_PATTERN = re.compile(
        r"^[\s\xa0]*(?://|#|--|/\*|<!--|%|REM)?[\s\xa0*#=\-_~]*(?:\b(?:END|STOP)\b|代码结束|结束编写(?:你的)?代码|结束(?:答题|编写|作答)?)[\s\xa0*#=\-_~]*(?:\*/|-->)?[\s\xa0]*$",
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

        # 5. 探测 SQL 数据库方言 (如 mysql, sqlserver, postgresql, oracle)
        combined_text = f"{title}\n{desc}\n{left_sections.get('requirements', '')}\n{left_sections.get('eval_instructions', '')}"
        db_dialect = self.detect_sql_dialect(text=combined_text, code=code)
        if db_dialect and (not language or language == "sql"):
            language = "sql"

        # 若识别出数据库方言，在 desc 开头注入醒目标记，赋能 Agent 推理
        if db_dialect:
            desc = f"> [!NOTE] 经检测本关卡数据库方言为: {db_dialect}\n\n{desc}"

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

        metadata = {
            "has_target_marker": has_marker,
            "language": language,
            "editor_type": editor_type,
            "code_length": len(code),
        }
        if db_dialect:
            metadata["db_dialect"] = db_dialect

        return QuestionData(
            type=QuestionType.PRACTICAL,
            title=title,
            description=desc,
            options=[],
            blanks=[],
            practical_details=practical_details,
            metadata=metadata,
        )

    @staticmethod
    def detect_sql_dialect(text: str = "", code: str = "") -> Optional[str]:
        """探测 SQL 实训题目所属的数据库引擎方言 (如 sqlserver, mysql, postgresql, oracle)。

        Args:
            text: 题干描述与要求文本
            code: 编辑器中已有模板或代码

        Returns:
            Optional[str]: 方言标识或 None
        """
        combined = f"{text}\n{code}".strip()
        if not combined:
            return None

        # 1. SQL Server / T-SQL 特征
        sqlserver_patterns = [
            r"(?m)^\s*GO\s*$",
            r"\bsys\.databases\b",
            r"\bsysobjects\b",
            r"\bsp_\w+",
            r"\bIDENTITY\s*\(",
            r"\bsqlserver\b",
            r"\bt-sql\b",
            r"\bmssql\b",
            r"\bTOP\s+\d+\b",
        ]
        if any(re.search(pat, combined, re.IGNORECASE) for pat in sqlserver_patterns):
            return "sqlserver"

        # 2. PostgreSQL 特征
        pg_patterns = [
            r"\bSERIAL\b",
            r"\bpg_catalog\b",
            r"\bpg_\w+",
            r"\bpostgresql\b",
            r"\bpostgres\b",
        ]
        if any(re.search(pat, combined, re.IGNORECASE) for pat in pg_patterns):
            return "postgresql"

        # 3. Oracle 特征
        oracle_patterns = [
            r"\bVARCHAR2\b",
            r"\bNUMBER\s*\(",
            r"\boracle\b",
            r"\bFROM\s+DUAL\b",
        ]
        if any(re.search(pat, combined, re.IGNORECASE) for pat in oracle_patterns):
            return "oracle"

        # 4. MySQL 特征
        mysql_patterns = [
            r"\bAUTO_INCREMENT\b",
            r"\binformation_schema\b",
            r"\bSHOW\s+DATABASES\b",
            r"\bENGINE\s*=\s*InnoDB\b",
            r"\bmysql\b",
            r"\bLIMIT\s+\d+\b",
        ]
        if any(re.search(pat, combined, re.IGNORECASE) for pat in mysql_patterns):
            return "mysql"

        return None

    @staticmethod
    def table_to_markdown(table_element: Tag) -> str:
        """将 HTML <table> 元素转换为标准格式的 Markdown 表格文本。

        支持自动对齐列数、表头识别与特殊符号转义，保留结构化数据字段。
        """
        if not table_element:
            return ""

        rows = table_element.find_all("tr")
        if not rows:
            return ""

        table_data: List[List[str]] = []
        for r in rows:
            cells = r.find_all(["th", "td"])
            if not cells:
                continue
            row_vals = []
            for c in cells:
                text = c.get_text(" ", strip=True)
                clean_cell = re.sub(r"\s+", " ", text).replace("|", "\\|")
                row_vals.append(clean_cell)
            if row_vals:
                table_data.append(row_vals)

        if not table_data:
            return ""

        max_cols = max(len(r) for r in table_data)
        if max_cols == 0:
            return ""

        normalized_data = []
        for r in table_data:
            padded = r + [""] * (max_cols - len(r))
            normalized_data.append(padded)

        header = normalized_data[0]
        separator = ["---"] * max_cols

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]

        for row in normalized_data[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    @staticmethod
    def clean_multimodal_elements(node: Tag) -> None:
        """提纯和规范化多模态元素（图片附件与嵌入图像），杜绝大段 base64 噪音涌入上下文。"""
        if not node:
            return

        for img in list(node.find_all("img")):
            src = img.get("src", "") or ""
            alt = (img.get("alt") or "").strip()
            title = (img.get("title") or "").strip()

            if "api/attachments" in src:
                name = alt or title
                if not name:
                    # 从 URL 路径截取文件名
                    clean_src = src.split("?")[0].split("#")[0]
                    name = clean_src.split("/")[-1] if "/" in clean_src else "附件图片"
                annot = f"[附图说明: {name or '附件图片'}]"
            elif src.startswith("data:image"):
                label = alt or title or "嵌入图像"
                annot = f"[图片: {label}]"
            elif src:
                clean_src = src.split("?")[0].split("#")[0]
                fname = clean_src.split("/")[-1] if "/" in clean_src else "插图"
                name = alt or title or fname or "插图"
                annot = f"[图片: {name}]"
            else:
                annot = ""

            if not annot:
                img.decompose()
                continue

            # 如果父节点为容器层（如 div），包装为 p 标签以便提取器结构化采集
            if img.parent and img.parent.name in ["p", "span", "td", "th", "li"]:
                img.replace_with(f" {annot} ")
            else:
                new_p = BeautifulSoup(f"<p>{annot}</p>", "html.parser").find("p")
                img.replace_with(new_p)

    def _extract_left_pane_sections(self, soup: BeautifulSoup) -> Dict[str, str]:
        """解析左侧面板的各个版块 (任务描述, 编程要求, 测试说明, 评测说明等)"""
        left_node: Optional[Tag] = None
        for selector in self.LEFT_PANE_SELECTORS:
            left_node = soup.select_one(selector)
            if left_node:
                break

        if not left_node:
            left_node = soup.body if soup.body else soup

        # 预先清洗图片等多模态元素
        self.clean_multimodal_elements(left_node)

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

        # 遍历所有标题、段落及表格元素
        elements = left_node.find_all(["h1", "h2", "h3", "h4", "h5", "p", "div", "pre", "ul", "ol", "table"])
        handled_tables = set()

        for elem in elements:
            # 处理表格元素
            if elem.name == "table":
                md_table = self.table_to_markdown(elem)
                if md_table:
                    sections[current_section].append(md_table)
                handled_tables.add(elem)
                continue

            # 若元素位于已处理的 table 内部，则跳过防止重复提取
            if any(parent in handled_tables for parent in elem.parents):
                continue

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
            if elem.name in ["p", "pre", "ul", "ol"] or (elem.name == "div" and not elem.find(["p", "div", "table"])):
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
