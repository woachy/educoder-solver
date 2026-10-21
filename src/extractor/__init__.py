"""全题型感知与提取器模块"""

from src.extractor.base import (
    BaseExtractor,
    BlankItem,
    ChoiceOption,
    PracticalDetails,
    QuestionData,
    QuestionType,
    SubQuestion,
    get_page_html,
)
from src.extractor.blank import BlankExtractor
from src.extractor.choice import ChoiceExtractor
from src.extractor.detector import detect_question_type, extract_question, wait_for_spa_loading
from src.extractor.paper import PaperExtractor, extract_latex_formulas
from src.extractor.practical import PracticalExtractor

__all__ = [
    "BaseExtractor",
    "BlankItem",
    "ChoiceOption",
    "PracticalDetails",
    "QuestionData",
    "QuestionType",
    "SubQuestion",
    "BlankExtractor",
    "ChoiceExtractor",
    "PaperExtractor",
    "PracticalExtractor",
    "detect_question_type",
    "extract_question",
    "extract_latex_formulas",
    "get_page_html",
    "wait_for_spa_loading",
]
