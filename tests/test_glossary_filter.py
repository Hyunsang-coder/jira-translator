"""Tests for 2-stage glossary filter: new format parsing + LLM filter."""
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Stub openai before import
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = MagicMock
    sys.modules["openai"] = openai_stub


# ---------------------------------------------------------------------------
# _load_glossary_terms: new category format
# ---------------------------------------------------------------------------

class TestLoadGlossaryTerms:
    def _make_engine(self):
        from modules.translation_engine import TranslationEngine
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.openai = MagicMock()
        engine.openai_model = "gpt-5.2"
        from prompts import PromptBuilder
        engine.prompt_builder = PromptBuilder({}, "")
        return engine

    def _mock_engine_base_dir(self, monkeypatch, tmp_path):
        import modules.translation_engine as te_mod

        # _load_glossary_terms 내부의 base_dir 계산을 tmp_path로 고정
        monkeypatch.setattr(
            te_mod.Path,
            "resolve",
            lambda self: tmp_path / "modules" / "translation_engine.py",
        )

    def test_flat_format(self, tmp_path, monkeypatch):
        engine = self._make_engine()
        self._mock_engine_base_dir(monkeypatch, tmp_path)
        glossary_dir = tmp_path / "glossaries"
        glossary_dir.mkdir(parents=True, exist_ok=True)
        (glossary_dir / "test.json").write_text(
            json.dumps({"terms": {"Ultimate": "궁극기", "Gadget": "가젯"}}, ensure_ascii=False),
            encoding="utf-8",
        )

        terms = engine._load_glossary_terms("test.json")
        assert terms == {"Ultimate": "궁극기", "Gadget": "가젯"}

    def test_category_format_flat_conversion(self, tmp_path, monkeypatch):
        """Category format (new) should be flattened to {en: ko}."""
        engine = self._make_engine()
        self._mock_engine_base_dir(monkeypatch, tmp_path)

        glossary_dir = tmp_path / "glossaries"
        glossary_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "glossary": {
                "Class/Skill": [
                    {"ko": "궁극기", "en": "Ultimate"},
                    {"ko": "가젯", "en": "Gadget"},
                    {"ko": "완전 무장", "en": "Locked & Loaded", "note": "스킬명"},
                    {"ko": "락앤로드", "en": "Locked & Loaded", "note": "대체 번역"},
                ],
                "Map": [
                    {"ko": "환전소", "en": "The Exchange"},
                ],
            }
        }
        (glossary_dir / "cat.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        terms = engine._load_glossary_terms("cat.json")

        assert terms["Ultimate"] == "궁극기"
        assert terms["Gadget"] == "가젯"
        assert terms["Locked & Loaded"] == "완전 무장 (스킬명)"
        assert terms["Locked & Loaded__2"] == "락앤로드 (대체 번역)"
        assert terms["The Exchange"] == "환전소"

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        engine = self._make_engine()
        self._mock_engine_base_dir(monkeypatch, tmp_path)
        (tmp_path / "glossaries").mkdir(parents=True, exist_ok=True)
        result = engine._load_glossary_terms("__nonexistent_file__.json")
        assert result == {}

    def test_empty_glossary_key_returns_empty(self, tmp_path, monkeypatch):
        engine = self._make_engine()
        self._mock_engine_base_dir(monkeypatch, tmp_path)

        glossary_dir = tmp_path / "glossaries"
        glossary_dir.mkdir(parents=True, exist_ok=True)
        (glossary_dir / "empty.json").write_text(
            json.dumps({"glossary": {}}, ensure_ascii=False),
            encoding="utf-8",
        )

        result = engine._load_glossary_terms("empty.json")
        assert result == {}


# ---------------------------------------------------------------------------
# get_candidate_terms (prompts.py)
# ---------------------------------------------------------------------------

class TestGetCandidateTerms:
    def _builder(self, terms):
        from prompts import PromptBuilder
        return PromptBuilder(terms, "Test")

    def test_eng_match(self):
        b = self._builder({"Ultimate": "궁극기", "Gadget": "가젯"})
        candidates = b.get_candidate_terms(["Use Ultimate skill"])
        assert "Ultimate" in candidates
        assert "Gadget" not in candidates

    def test_kor_match(self):
        b = self._builder({"Ultimate": "궁극기", "Gadget": "가젯"})
        candidates = b.get_candidate_terms(["궁극기 사용"])
        assert "Ultimate" in candidates
        assert "Gadget" not in candidates

    def test_no_match_returns_empty(self):
        b = self._builder({"Ultimate": "궁극기"})
        candidates = b.get_candidate_terms(["completely unrelated text"])
        assert candidates == {}

    def test_empty_terms_returns_empty(self):
        b = self._builder({})
        assert b.get_candidate_terms(["Ultimate skill"]) == {}

    def test_word_boundary_no_false_positive(self):
        """'key' should not match 'monkey'."""
        b = self._builder({"key": "키"})
        candidates = b.get_candidate_terms(["monkey around"])
        assert "key" not in candidates


# ---------------------------------------------------------------------------
# _filter_glossary_by_llm
# ---------------------------------------------------------------------------

class TestFilterGlossaryByLlm:
    def _make_engine(self, terms=None):
        from modules.translation_engine import TranslationEngine
        engine = TranslationEngine.__new__(TranslationEngine)
        engine.openai = MagicMock()
        engine.openai_model = "gpt-5.2"
        from prompts import PromptBuilder
        engine.prompt_builder = PromptBuilder(terms or {}, "Test")
        return engine

    def test_below_threshold_skips_llm(self):
        """후보가 THRESHOLD 이하면 LLM 호출 없이 candidates 그대로 반환."""
        from models import GLOSSARY_FILTER_THRESHOLD
        engine = self._make_engine()
        small = {f"term{i}": f"용어{i}" for i in range(GLOSSARY_FILTER_THRESHOLD)}
        result = engine._filter_glossary_by_llm(small, ["some text"])
        assert result == small
        engine.openai.beta.chat.completions.parse.assert_not_called()
        engine.openai.chat.completions.create.assert_not_called()

    def test_above_threshold_calls_llm(self):
        """후보가 THRESHOLD 초과면 LLM 호출."""
        from models import GLOSSARY_FILTER_THRESHOLD
        import modules.translation_engine as te_mod

        engine = self._make_engine()
        large = {f"term{i}": f"용어{i}" for i in range(GLOSSARY_FILTER_THRESHOLD + 5)}

        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = (
            '{"selected_keys": ["term0", "term1"]}'
        )
        engine.openai.chat.completions.create.return_value = mock_completion

        with patch.object(te_mod, "PYDANTIC_AVAILABLE", False):
            result = engine._filter_glossary_by_llm(large, ["term0 term1 content"])

        assert set(result.keys()) == {"term0", "term1"}

    def test_llm_error_falls_back_to_candidates(self):
        """LLM 오류 시 전체 candidates 반환 (graceful fallback)."""
        from models import GLOSSARY_FILTER_THRESHOLD
        import modules.translation_engine as te_mod

        engine = self._make_engine()
        large = {f"term{i}": f"용어{i}" for i in range(GLOSSARY_FILTER_THRESHOLD + 5)}

        engine.openai.chat.completions.create.side_effect = RuntimeError("API error")

        with patch.object(te_mod, "PYDANTIC_AVAILABLE", False):
            result = engine._filter_glossary_by_llm(large, ["text"])

        assert result == large

    def test_empty_candidates_returns_empty(self):
        engine = self._make_engine()
        result = engine._filter_glossary_by_llm({}, ["text"])
        assert result == {}


# ---------------------------------------------------------------------------
# build_glossary_instruction uses filtered candidates
# ---------------------------------------------------------------------------

class TestBuildGlossaryInstructionWithFilter:
    def test_instruction_built_from_filtered_terms(self):
        from prompts import PromptBuilder
        b = PromptBuilder({"Ultimate": "궁극기", "Gadget": "가젯"}, "Heist")
        # Only 'Ultimate' appears in text
        instruction = b.build_glossary_instruction(["Use the Ultimate skill"])
        assert "Ultimate" in instruction
        assert "Gadget" not in instruction
