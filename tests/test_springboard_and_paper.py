"""试卷型大题、跳板详情页穿透与关卡导航测试 (Springboard, Paper & Stage Tests).

验证:
1. 页面类型精准解耦与判定 (is_classroom_page, is_springboard_page, is_shixun_task_page)
2. BrowserSession get_target_page 偏好路由 (classroom, springboard, shixun, any)
3. 跳板页穿透 (penetrate_detail_springboard) 与开启/继续挑战按钮定位
4. 评测按钮多态定位器与 PREV_LEVEL_SELECTORS 覆盖
5. LaTeX 公式提取 (KaTeX, MathJax, 属性, 文本) 与试卷型题目抽取 (PaperExtractor)
6. 试卷型答案批量拟真提交 (submit_paper_answers)
7. 关卡拓扑感知与自动回退对齐 (detect_stage_topology, align_to_first_uncompleted_stage)
8. CLI 子命令 submit-paper 与 navigate-stage 解析与调用
"""

import json
from unittest.mock import MagicMock, call, patch
import pytest
from bs4 import BeautifulSoup

from src.browser.manager import (
    BrowserSession,
    is_classroom_page,
    is_shixun_task_page,
    is_springboard_page,
)
from src.cli import build_parser, main
from src.executor.classroom_orchestrator import (
    INNER_CHALLENGE_BUTTON_SELECTORS,
    penetrate_detail_springboard,
)
from src.executor.eval_action import EvaluationManager
from src.executor.paper_action import submit_paper_answers
from src.executor.stage_navigator import (
    align_to_first_uncompleted_stage,
    detect_stage_topology,
    navigate_to_stage,
    trigger_prev_stage,
)
from src.extractor.base import BlankItem, ChoiceOption, QuestionData, QuestionType, SubQuestion
from src.extractor.paper import PaperExtractor, extract_latex_formulas


# =====================================================================
# 1. 页面分类与定向路由判定测试
# =====================================================================

class TestPageClassification:
    """测试页面解耦分类器"""

    def test_is_classroom_page(self):
        p1 = MagicMock()
        p1.url = "https://www.educoder.net/classrooms/1024/shixun_homework"
        assert is_classroom_page(p1) is True

        p2 = MagicMock()
        p2.url = "https://www.educoder.net/classrooms/1024/homeworks"
        assert is_classroom_page(p2) is True

        p3 = MagicMock()
        p3.url = "https://www.educoder.net/classrooms"  # 纯全局班级列表，非特定作业列表
        assert is_classroom_page(p3) is False

        p4 = MagicMock()
        p4.url = "https://www.educoder.net/shixuns/abc/detail?tabs=1"
        assert is_classroom_page(p4) is False

        p5 = MagicMock()
        p5.url = "https://www.educoder.net/tasks/xyz"
        assert is_classroom_page(p5) is False

    def test_is_springboard_page(self):
        p1 = MagicMock()
        p1.url = "https://www.educoder.net/shixuns/abc123/detail?tabs=1"
        assert is_springboard_page(p1) is True

        p2 = MagicMock()
        p2.url = "https://www.educoder.net/shixuns/abc123/detail"
        assert is_springboard_page(p2) is True

        p3 = MagicMock()
        p3.url = "https://www.educoder.net/tasks/abc123"
        assert is_springboard_page(p3) is False

        p4 = MagicMock()
        p4.url = "https://www.educoder.net/classrooms/1024/shixun_homework"
        assert is_springboard_page(p4) is False

    def test_is_shixun_task_page(self):
        p1 = MagicMock()
        p1.url = "https://www.educoder.net/tasks/abc123"
        assert is_shixun_task_page(p1) is True

        p2 = MagicMock()
        p2.url = "https://www.educoder.net/shixuns/abc123/challenges"
        assert is_shixun_task_page(p2) is True

        p3 = MagicMock()
        p3.url = "https://www.educoder.net/shixuns/abc123/detail?tabs=1"
        assert is_shixun_task_page(p3) is False

        p4 = MagicMock()
        p4.url = "https://www.educoder.net/classrooms/1024/shixun_homework"
        assert is_shixun_task_page(p4) is False


class TestBrowserSessionPreferRouting:
    """测试 BrowserSession 的 prefer_type 路由选择"""

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.sync_playwright")
    def test_prefer_springboard_routing(self, mock_playwright_cm, mock_check_cdp):
        p_shixun = MagicMock()
        p_shixun.url = "https://www.educoder.net/tasks/task1"
        p_spring = MagicMock()
        p_spring.url = "https://www.educoder.net/shixuns/detail1/detail?tabs=1"
        p_class = MagicMock()
        p_class.url = "https://www.educoder.net/classrooms/10/shixun_homework"

        mock_browser = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.pages = [p_shixun, p_spring, p_class]
        mock_browser.contexts = [mock_ctx]
        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222) as session:
            # prefer_type = springboard 应优先匹配 p_spring
            target = session.get_target_page("educoder.net", prefer_type="springboard", auto_penetrate=False)
            assert target == p_spring

    @patch("src.browser.manager.check_cdp_available", return_value=True)
    @patch("src.browser.manager.sync_playwright")
    def test_prefer_shixun_ignores_springboard(self, mock_playwright_cm, mock_check_cdp):
        p_spring = MagicMock()
        p_spring.url = "https://www.educoder.net/shixuns/detail1/detail?tabs=1"
        p_shixun = MagicMock()
        p_shixun.url = "https://www.educoder.net/tasks/real_task"

        mock_browser = MagicMock()
        mock_ctx = MagicMock()
        # 跳板页在前，关卡做题页在后
        mock_ctx.pages = [p_spring, p_shixun]
        mock_browser.contexts = [mock_ctx]
        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp.return_value = mock_browser
        mock_playwright_cm.return_value.start.return_value = mock_playwright

        with BrowserSession(port=9222) as session:
            # prefer_type = shixun 必须优先命中 p_shixun，而不被残留的跳板页劫持
            target = session.get_target_page("educoder.net", prefer_type="shixun", auto_penetrate=False)
            assert target == p_shixun


# =====================================================================
# 2. 跳板详情页穿透测试
# =====================================================================

class TestSpringboardPenetration:
    """测试跳板页穿透与开启挑战按钮定位"""

    def test_penetrate_noop_when_already_task_page(self):
        mock_page = MagicMock()
        mock_page.url = "https://www.educoder.net/tasks/123"
        mock_elem = MagicMock()
        mock_page.query_selector.return_value = mock_elem

        # 已有关卡容器，直接原样返回
        res_page = penetrate_detail_springboard(mock_page)
        assert res_page == mock_page

    def test_penetrate_clicks_challenge_button(self):
        mock_page = MagicMock()
        mock_page.url = "https://www.educoder.net/shixuns/abc/detail?tabs=1"
        mock_btn = MagicMock()
        mock_btn.is_visible.return_value = True

        # 模拟第一次 query_selector 找到开启挑战按钮
        mock_page.query_selector.return_value = mock_btn

        mock_new_page = MagicMock()
        mock_new_page.url = "https://www.educoder.net/tasks/abc"
        mock_ctx = MagicMock()
        mock_ctx.pages = [mock_page, mock_new_page]
        mock_ctx.expect_page.return_value.__enter__.return_value.value = mock_new_page

        with patch("src.executor.classroom_orchestrator.random_delay"):
            res_page = penetrate_detail_springboard(mock_page, context=mock_ctx)
            mock_btn.click.assert_called_once()
            assert res_page == mock_new_page


# =====================================================================
# 3. 评测按钮与上一关按钮定位多态性
# =====================================================================

class TestEvalButtonPolymorphism:
    """测试评测按钮与上一关按钮多态定位器"""

    def test_eval_button_selectors_coverage(self):
        mgr = EvaluationManager()
        # 确保哈希混淆类名与语义属性被包含
        assert any("btn-run" in sel for sel in mgr.EVAL_BUTTON_SELECTORS)
        assert any("运行评测" in sel for sel in mgr.EVAL_BUTTON_SELECTORS)
        assert any("评测" in sel for sel in mgr.EVAL_BUTTON_SELECTORS)

    def test_prev_level_selectors_coverage(self):
        mgr = EvaluationManager()
        assert len(mgr.PREV_LEVEL_SELECTORS) >= 3
        assert any("上一关" in sel for sel in mgr.PREV_LEVEL_SELECTORS)

    def test_find_eval_button_retry_success(self):
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.is_visible.return_value = True

        # 首轮未找到，第二轮找到
        mock_page.query_selector.side_effect = [None, None, mock_btn]

        mgr = EvaluationManager()
        with patch("src.executor.eval_action.random_delay"):
            found = mgr.find_eval_button(mock_page, timeout=1.0)
            assert found == mock_btn


# =====================================================================
# 4. LaTeX 数学公式提取与试卷题目抽取测试
# =====================================================================

class TestPaperExtractor:
    """测试试卷型与复合客观/填空题提取器"""

    def test_extract_latex_formulas(self):
        html = """
        <div>
            <span class="katex">
                <annotation encoding="application/x-tex">\\sigma_{A=B}(R)</annotation>
            </span>
            <script type="math/tex">\\pi_{C, D}(S)</script>
            <span data-latex="R \\bowtie S"></span>
            <p>计算公式为 $X \\cup Y$ 的结果</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        formulas = extract_latex_formulas(soup)

        assert "\\sigma_{A=B}(R)" in formulas
        assert "\\pi_{C, D}(S)" in formulas
        assert "R \\bowtie S" in formulas
        assert "X \\cup Y" in formulas

    def test_paper_extractor_mixed_questions(self):
        html = """
        <div class="exam-paper-container">
            <div class="question-item" data-index="1">
                <div class="question-title">1. 下列关于关系代数运算中，选择操作表示为：</div>
                <div class="katex"><annotation encoding="application/x-tex">\\sigma</annotation></div>
                <ul class="options-list">
                    <li class="option-item"><input type="radio" value="A"/> A. \\sigma</li>
                    <li class="option-item"><input type="radio" value="B"/> B. \\pi</li>
                </ul>
            </div>
            <div class="question-item" data-index="2">
                <div class="question-title">2. 关系模型中，自然连接的符号是</div>
                <div class="blank-fill">
                    <input class="blank-input" type="text" placeholder="输入答案"/>
                </div>
            </div>
        </div>
        """
        extractor = PaperExtractor()
        q_data = extractor.extract(html)

        assert q_data.type == QuestionType.EXAM_PAPER
        assert len(q_data.sub_questions) == 2

        # 检查子题 1 (选择题)
        sq1 = q_data.sub_questions[0]
        assert sq1.index == 1
        assert sq1.type == QuestionType.CHOICE
        assert len(sq1.options) == 2
        assert "\\sigma" in sq1.latex_formulas

        # 检查子题 2 (填空题)
        sq2 = q_data.sub_questions[1]
        assert sq2.index == 2
        assert sq2.type == QuestionType.BLANK
        assert len(sq2.blanks) == 1


# =====================================================================
# 5. 试卷型大题拟真提交测试
# =====================================================================

class TestPaperAction:
    """测试试卷型答题提交与作用域隔离"""

    def test_submit_paper_answers_success(self):
        mock_page = MagicMock()
        mock_container1 = MagicMock()
        mock_container2 = MagicMock()

        # 模拟 2 个子题容器
        mock_page.query_selector_all.return_value = [mock_container1, mock_container2]

        opt_a = MagicMock()
        opt_a.inner_text.return_value = "A. 选择"
        opt_a.get_attribute.return_value = ""
        mock_container1.query_selector_all.return_value = [opt_a]

        input_box = MagicMock()
        mock_container2.query_selector_all.return_value = [input_box]

        q_data = QuestionData(
            type=QuestionType.EXAM_PAPER,
            title="数据库试卷测试",
            sub_questions=[
                SubQuestion(
                    index=1,
                    type=QuestionType.CHOICE,
                    title="题目1",
                    options=[ChoiceOption(id="A", text="选择", selected=False, selector=".opt-a")],
                ),
                SubQuestion(
                    index=2,
                    type=QuestionType.BLANK,
                    title="题目2",
                    blanks=[BlankItem(index=1, selector="input.blank-input")],
                ),
            ],
        )

        with patch("src.executor.paper_action.extract_question", return_value=q_data), \
             patch("src.executor.paper_action.random_delay"), \
             patch("src.executor.paper_action._fill_single_blank", return_value=True):

            answers_map = {1: "A", 2: ["自然连接"]}
            res = submit_paper_answers(mock_page, answers_map, auto_eval=False)

            assert res["status"] == "success"
            assert res["success_count"] == 2
            assert res["total_submitted"] == 2


# =====================================================================
# 6. 多关卡拓扑感知与自动回退测试
# =====================================================================

class TestStageNavigator:
    """测试关卡拓扑与回退对齐"""

    def test_detect_stage_topology_from_text(self):
        mock_page = MagicMock()
        mock_page.evaluate.return_value = "当前进度：第 2 关 / 共 3 关\n请编写 SQL 语句"
        mock_page.query_selector.return_value = None
        mock_page.query_selector_all.return_value = []

        topo = detect_stage_topology(mock_page)
        assert topo["current_stage"] == 2
        assert topo["total_stages"] == 3

    def test_trigger_prev_stage(self):
        mock_page = MagicMock()
        with patch.object(EvaluationManager, "trigger_prev_level", return_value=True) as mock_prev:
            ok = trigger_prev_stage(mock_page)
            assert ok is True
            mock_prev.assert_called_once_with(mock_page)

    def test_align_to_first_uncompleted_stage(self):
        mock_page = MagicMock()

        # 模拟第 1 次检测在第 2 关，回退后在第 1 关
        topo1 = {"current_stage": 2, "total_stages": 2, "has_prev": True}
        topo2 = {"current_stage": 1, "total_stages": 2, "has_prev": False}

        with patch("src.executor.stage_navigator.detect_stage_topology", side_effect=[topo1, topo2]), \
             patch("src.executor.stage_navigator.trigger_prev_stage", return_value=True), \
             patch("src.executor.stage_navigator.random_delay"):

            res = align_to_first_uncompleted_stage(mock_page, max_rollbacks=3)
            assert res["current_stage"] == 1
            assert res["rollbacks_performed"] == 1


# =====================================================================
# 7. CLI 命令与参数解析测试
# =====================================================================

class TestCliExtensions:
    """测试新注册的 CLI 命令与参数解析"""

    def test_parser_submit_paper(self):
        parser = build_parser()
        args = parser.parse_args(["submit-paper", "--answers", '{"1": "A", "2": ["ans"]}', "--eval", "--json"])
        assert args.command == "submit-paper"
        assert args.answers == '{"1": "A", "2": ["ans"]}'
        assert args.eval is True
        assert args.json is True

    def test_parser_navigate_stage(self):
        parser = build_parser()
        args = parser.parse_args(["navigate-stage", "--align-first", "--json"])
        assert args.command == "navigate-stage"
        assert args.align_first is True
        assert args.json is True

    def test_cmd_submit_paper_execution(self, capsys):
        fake_result = {
            "status": "success",
            "success_count": 1,
            "total_submitted": 1,
            "message": "全部子题目作答完成",
        }
        with patch("src.cli.BrowserSession"), \
             patch("src.cli.submit_paper_answers", return_value=fake_result):
            main(["submit-paper", "--answers", '{"1": "A"}', "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["status"] == "success"
            assert data["success_count"] == 1

    def test_cmd_navigate_stage_align_execution(self, capsys):
        fake_result = {
            "initial_stage": 2,
            "current_stage": 1,
            "rollbacks_performed": 1,
        }
        with patch("src.cli.BrowserSession"), \
             patch("src.cli.align_to_first_uncompleted_stage", return_value=fake_result):
            main(["navigate-stage", "--align-first", "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert data["current_stage"] == 1
            assert data["rollbacks_performed"] == 1
