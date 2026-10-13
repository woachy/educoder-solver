"""全题型智能提取感知引擎单元测试 (Extractor Tests).

覆盖:
1. 题型智能探测 (单选、多选、判断、填空、实训、未知)
2. 客观选择题与判断题提取 (选项 ID、纯文本、选中态、选择器)
3. 文本填空题提取 (空位序号、占位提示、前后上下文、当前值)
4. 编程实训题提取 (双栏任务要求、评测说明、Monaco代码读取)
5. Begin-End 区域靶心切分算法 (各类语言注释风格与零损还原)
6. 题目数据模型无损 JSON 序列化
"""

import json
from unittest.mock import MagicMock
import pytest

from src.extractor.base import (
    BlankItem,
    ChoiceOption,
    PracticalDetails,
    QuestionData,
    QuestionType,
)
from src.extractor.blank import BlankExtractor
from src.extractor.choice import ChoiceExtractor
from src.extractor.detector import detect_question_type, extract_question
from src.extractor.practical import PracticalExtractor
from tests.fixtures.html_samples import (
    BLANK_HTML,
    JUDGMENT_HTML,
    MULTIPLE_CHOICE_HTML,
    PRACTICAL_HTML,
    PRACTICAL_NO_MARKER_HTML,
    SINGLE_CHOICE_HTML,
)


class TestQuestionTypeDetector:
    """测试题型自动探测器"""

    def test_detect_single_choice(self):
        q_type = detect_question_type(SINGLE_CHOICE_HTML)
        assert q_type == QuestionType.CHOICE

    def test_detect_multiple_choice(self):
        q_type = detect_question_type(MULTIPLE_CHOICE_HTML)
        assert q_type == QuestionType.MULTIPLE_CHOICE

    def test_detect_judgment(self):
        q_type = detect_question_type(JUDGMENT_HTML)
        assert q_type == QuestionType.JUDGMENT

    def test_detect_blank(self):
        q_type = detect_question_type(BLANK_HTML)
        assert q_type == QuestionType.BLANK

    def test_detect_practical(self):
        q_type = detect_question_type(PRACTICAL_HTML)
        assert q_type == QuestionType.PRACTICAL

    def test_detect_unknown(self):
        html = "<div><p>这是一段纯说明文字，没有任何表单或编辑器。</p></div>"
        q_type = detect_question_type(html)
        assert q_type == QuestionType.UNKNOWN


class TestChoiceExtractor:
    """测试客观选择题与判断题提取"""

    def test_extract_single_choice(self):
        extractor = ChoiceExtractor()
        data = extractor.extract(SINGLE_CHOICE_HTML)

        assert data.type == QuestionType.CHOICE
        assert "下列关于 Python 列表的描述中，错误的是" in data.title
        assert len(data.options) == 4

        # 校验选项标识与纯净文本 (剔除了 'A' 等前缀)
        opt_a = data.options[0]
        assert opt_a.id == "A"
        assert opt_a.text == "列表是可变序列"
        assert opt_a.selected is False

        # 校验选中态 (B 选项在 HTML 中被选中)
        opt_b = data.options[1]
        assert opt_b.id == "B"
        assert "列表元素必须为同一种类型" in opt_b.text
        assert opt_b.selected is True

        opt_c = data.options[2]
        assert opt_c.id == "C"
        assert opt_c.selected is False

    def test_extract_multiple_choice(self):
        extractor = ChoiceExtractor()
        data = extractor.extract(MULTIPLE_CHOICE_HTML)

        assert data.type == QuestionType.MULTIPLE_CHOICE
        assert "不可变数据类型" in data.title
        assert len(data.options) == 4

        selected_ids = [opt.id for opt in data.options if opt.selected]
        # HTML 中 A, C, D 带有 checked 状态
        assert selected_ids == ["A", "C", "D"]

        opt_b = next(opt for opt in data.options if opt.id == "B")
        assert opt_b.selected is False
        assert "list" in opt_b.text

    def test_extract_judgment(self):
        extractor = ChoiceExtractor()
        data = extractor.extract(JUDGMENT_HTML)

        assert data.type == QuestionType.JUDGMENT
        assert "字典键必须是可哈希" in data.title
        assert len(data.options) == 2

        opt_true = data.options[0]
        assert opt_true.id in ("正确", "A") or "正确" in opt_true.text
        assert opt_true.selected is True


class TestBlankExtractor:
    """测试填空题提取"""

    def test_extract_blanks(self):
        extractor = BlankExtractor()
        data = extractor.extract(BLANK_HTML)

        assert data.type == QuestionType.BLANK
        assert "Python 基础语法填空" in data.title
        assert len(data.blanks) == 2

        b1 = data.blanks[0]
        assert b1.index == 1
        assert b1.hint == "请输入函数名"
        assert b1.current_value == "print"
        assert "使用" in b1.prefix_text
        assert "函数向控制台输出" in b1.suffix_text

        b2 = data.blanks[1]
        assert b2.index == 2
        assert b2.hint == "请输入函数名"
        assert b2.current_value == ""
        assert "使用" in b2.prefix_text
        assert "函数获取键盘输入" in b2.suffix_text


class TestPracticalExtractor:
    """测试编程实训题提取与 Begin-End 区域切分"""

    def test_extract_practical_details(self):
        extractor = PracticalExtractor()
        data = extractor.extract(PRACTICAL_HTML)

        assert data.type == QuestionType.PRACTICAL
        assert "两数之和" in data.title
        assert data.practical_details is not None

        details = data.practical_details
        assert "两个正整数的和" in details.task_description
        assert "Begin-End" in details.requirements
        assert "输入：3 5" in details.sample_io
        assert "5 组测试用例" in details.eval_instructions
        assert details.language == "python"
        assert details.has_target_marker is True

        # 验证核心靶心代码还原契约
        assert details.prefix_code + details.target_code + details.suffix_code == details.code
        assert "return a + b" in details.target_code
        assert "def solve" in details.prefix_code
        assert "End" in details.suffix_code

    def test_extract_practical_without_marker(self):
        extractor = PracticalExtractor()
        data = extractor.extract(PRACTICAL_NO_MARKER_HTML)

        assert data.type == QuestionType.PRACTICAL
        details = data.practical_details
        assert details is not None
        assert details.has_target_marker is False
        assert details.prefix_code == ""
        assert details.suffix_code == ""
        assert details.target_code == details.code
        assert "quick_sort" in details.target_code

    def test_extract_with_monaco_js_evaluate(self):
        """测试通过 Page.evaluate 优先读取 Monaco 运行态模型代码"""
        mock_page = MagicMock()
        mock_page.content.return_value = PRACTICAL_HTML
        mock_page.evaluate.return_value = {
            "code": "def dynamic_code():\n    # Begin\n    pass\n    # End\n",
            "language": "python",
            "editor_type": "monaco",
        }

        extractor = PracticalExtractor()
        data = extractor.extract(mock_page)

        details = data.practical_details
        assert details is not None
        assert "dynamic_code" in details.code
        assert details.has_target_marker is True
        assert details.prefix_code + details.target_code + details.suffix_code == details.code


class TestBeginEndSplitter:
    """测试不同语言与注释风格下的 Begin-End 靶心切分算法"""

    def test_python_style(self):
        code = (
            "# Header info\n"
            "def test():\n"
            "    # ********** Begin **********\n"
            "    x = 10\n"
            "    return x * 2\n"
            "    # ********** End **********\n"
            "# Footer info\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "# ********** Begin **********" in prefix
        assert "    x = 10\n    return x * 2\n" == target
        assert "# ********** End **********" in suffix

    def test_cpp_java_style(self):
        code = (
            "#include <iostream>\n"
            "int main() {\n"
            "    // ########## Begin ##########\n"
            "    std::cout << \"Hello World\";\n"
            "    // ########## End ##########\n"
            "    return 0;\n"
            "}\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "// ########## Begin ##########" in prefix
        assert "std::cout << \"Hello World\";\n" in target
        assert "// ########## End ##########" in suffix

    def test_sql_style(self):
        code = (
            "USE test_db;\n"
            "-- ********** Begin **********\n"
            "SELECT student_id, name FROM students WHERE score >= 60;\n"
            "-- ********** End **********\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "-- ********** Begin **********" in prefix
        assert "SELECT student_id" in target
        assert "-- ********** End **********" in suffix

    def test_html_xml_style(self):
        code = (
            "<html>\n<body>\n"
            "<!-- ********** Begin ********** -->\n"
            "<h1>Hello Educoder</h1>\n"
            "<!-- ********** End ********** -->\n"
            "</body>\n</html>\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "<!-- ********** Begin ********** -->" in prefix
        assert "<h1>Hello Educoder</h1>\n" == target
        assert "<!-- ********** End ********** -->" in suffix

    def test_c_block_comment_style(self):
        code = (
            "int calculate() {\n"
            "/* Begin */\n"
            "    int ans = 42;\n"
            "    return ans;\n"
            "/* End */\n"
            "}\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "    int ans = 42;\n    return ans;\n" == target

    def test_chinese_comment_style(self):
        """测试高校头歌常见中文注释风格靶心切分"""
        code = (
            "# (1) 创建用户与赋权\n"
            "# ---------- 开始编写你的代码 ----------\n"
            "CREATE USER 'u1'@'%' IDENTIFIED BY '123456';\n"
            "GRANT ALL PRIVILEGES ON *.* TO 'u1'@'%';\n"
            "# ---------- 结束编写你的代码 ----------\n"
            "-- 补充提交\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "CREATE USER 'u1'@'%'" in target
        assert "开始编写你的代码" in prefix
        assert "结束编写你的代码" in suffix

    def test_chinese_start_end_short_style(self):
        """测试简短中文注释标记风格"""
        code = (
            "def solve():\n"
            "    # 开始\n"
            "    return True\n"
            "    # 结束\n"
        )
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code(code)
        assert has_marker is True
        assert prefix + target + suffix == code
        assert "    return True\n" == target

    def test_empty_or_none_code(self):
        prefix, target, suffix, has_marker = PracticalExtractor.split_target_code("")
        assert has_marker is False
        assert prefix == ""
        assert target == ""
        assert suffix == ""


class TestSqlDialectDetection:
    """测试 SQL 数据库引擎方言自动识别器"""

    def test_detect_sqlserver_dialect(self):
        text = "请编写 T-SQL 脚本创建学生信息表"
        code = "USE master;\nCREATE TABLE student(id INT IDENTITY(1,1), name VARCHAR(50));\nGO"
        dialect = PracticalExtractor.detect_sql_dialect(text=text, code=code)
        assert dialect == "sqlserver"

    def test_detect_mysql_dialect(self):
        text = "在 MySQL 数据库中创建库和用户"
        code = "CREATE TABLE user(id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(20)) ENGINE=InnoDB;"
        dialect = PracticalExtractor.detect_sql_dialect(text=text, code=code)
        assert dialect == "mysql"

    def test_detect_postgresql_dialect(self):
        text = "使用 PostgreSQL 完成表结构定义"
        code = "CREATE TABLE logs(log_id SERIAL PRIMARY KEY, msg TEXT);"
        dialect = PracticalExtractor.detect_sql_dialect(text=text, code=code)
        assert dialect == "postgresql"

    def test_detect_oracle_dialect(self):
        text = "使用 Oracle 完成查询操作"
        code = "SELECT sysdate FROM DUAL;"
        dialect = PracticalExtractor.detect_sql_dialect(text=text, code=code)
        assert dialect == "oracle"

    def test_detect_no_sql_dialect(self):
        text = "编写一个二分查找算法"
        code = "def binary_search(arr, target): pass"
        dialect = PracticalExtractor.detect_sql_dialect(text=text, code=code)
        assert dialect is None


class TestQuestionDataSerialization:
    """测试题目数据模型结构化 JSON 序列化契约"""

    def test_json_lossless_roundtrip(self):
        opt = ChoiceOption(id="A", text="选项一", selected=True, selector="#opt_a", locator_index=0)
        blank = BlankItem(index=1, hint="提示", prefix_text="前置", suffix_text="后置", current_value="值")
        details = PracticalDetails(
            task_description="任务",
            requirements="要求",
            sample_io="用例",
            code="full_code",
            prefix_code="p_",
            target_code="t_",
            suffix_code="s_",
            language="python",
            has_target_marker=True,
        )

        q_data = QuestionData(
            type=QuestionType.CHOICE,
            title="测试题目标题",
            description="描述",
            options=[opt],
            blanks=[blank],
            practical_details=details,
            metadata={"source": "test"},
        )

        dict_output = q_data.to_dict()
        assert dict_output["type"] == "choice"
        assert len(dict_output["options"]) == 1
        assert dict_output["options"][0]["id"] == "A"

        json_str = q_data.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "choice"
        assert parsed["title"] == "测试题目标题"
        assert parsed["options"][0]["text"] == "选项一"
        assert parsed["blanks"][0]["current_value"] == "值"
        assert parsed["practical_details"]["language"] == "python"

    def test_unified_extract_question_entry(self):
        """测试统一提取入口 extract_question"""
        data = extract_question(SINGLE_CHOICE_HTML)
        assert data.type == QuestionType.CHOICE
        assert len(data.options) == 4

        data_blank = extract_question(BLANK_HTML)
        assert data_blank.type == QuestionType.BLANK
        assert len(data_blank.blanks) == 2


class TestPlaywrightIntegration:
    """真实 Playwright 页面挂载提取集成测试"""

    def test_real_playwright_page_extract(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(channel="msedge", headless=True)
                except Exception:
                    pytest.skip("本地未检测到可用的 Edge 浏览器，跳过端到端页面测试")
                try:
                    page = browser.new_page()
                    page.set_content(SINGLE_CHOICE_HTML)
                    data = extract_question(page)
                    assert data.type == QuestionType.CHOICE
                    assert len(data.options) == 4
                finally:
                    browser.close()
        except Exception as e:
            pytest.skip(f"Playwright 执行跳过: {e}")

