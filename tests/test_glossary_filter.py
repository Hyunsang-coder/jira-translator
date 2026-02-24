"""Tests for glossary filtering pipeline: loading + lexical filter + LLM filter."""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Stub openai before import
if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = MagicMock
    sys.modules["openai"] = openai_stub

from models import GlossaryEntry


class TestLoadGlossaryTerms:
    def _make_engine(self):
        from modules.translation_engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.openai = MagicMock()
        engine.openai_model = "gpt-5.2"
        from prompts import PromptBuilder

        engine.prompt_builder = PromptBuilder({}, "")
        engine._last_loaded_glossary_entries = []
        return engine

    def _mock_engine_base_dir(self, monkeypatch, tmp_path):
        import modules.translation_engine as te_mod

        # _load_glossary_entries 내부의 base_dir 계산을 tmp_path로 고정
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
        assert len(engine._last_loaded_glossary_entries) == 2

    def test_category_format_flat_conversion(self, tmp_path, monkeypatch):
        """Category format (legacy) should be flattened with duplicate-id suffix."""
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

    def test_entries_format_with_aliases(self, tmp_path, monkeypatch):
        engine = self._make_engine()
        self._mock_engine_base_dir(monkeypatch, tmp_path)

        glossary_dir = tmp_path / "glossaries"
        glossary_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [
                {
                    "id": "marksman_role",
                    "en": "Marksman",
                    "ko": "저격수",
                    "note": "플레이어 롤/클래스",
                    "category": "Class/Role",
                    "aliases_en": ["Sniper"],
                    "aliases_ko": ["스나이퍼"],
                }
            ]
        }
        (glossary_dir / "entry.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        terms = engine._load_glossary_terms("entry.json")
        assert terms["marksman_role"] == "저격수 (플레이어 롤/클래스)"

        entries = engine._last_loaded_glossary_entries
        assert len(entries) == 1
        assert entries[0].id == "marksman_role"
        assert entries[0].aliases_en == ("Sniper",)
        assert entries[0].aliases_ko == ("스나이퍼",)

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


class TestGetCandidateTerms:
    def _builder(self, terms):
        from prompts import PromptBuilder

        return PromptBuilder(terms, "Test")

    def test_alias_match_from_entries(self):
        from prompts import PromptBuilder

        b = PromptBuilder(
            glossary_terms={},
            glossary_name="Test",
            glossary_entries=[
                GlossaryEntry(
                    id="marksman_role",
                    en="Marksman",
                    ko="저격수",
                    aliases_en=("Sniper",),
                    aliases_ko=("스나이퍼",),
                )
            ],
        )
        en_candidates = b.get_candidate_terms(["Sniper role selected"], source_lang="en")
        ko_candidates = b.get_candidate_terms(["스나이퍼를 선택합니다"], source_lang="ko")
        assert "marksman_role" in en_candidates
        assert "marksman_role" in ko_candidates

    def test_eng_match(self):
        b = self._builder({"Ultimate": "궁극기", "Gadget": "가젯"})
        candidates = b.get_candidate_terms(["Use Ultimate skill"], source_lang="en")
        assert "Ultimate" in candidates
        assert "Gadget" not in candidates

    def test_kor_match_with_note_value(self):
        b = self._builder({"Marksman": "저격수 (플레이어 롤/클래스)"})
        candidates = b.get_candidate_terms(["저격수를 선택합니다"], source_lang="ko")
        assert "Marksman" in candidates

    def test_punctuation_wrapped_english_term_matches(self):
        b = self._builder({
            '.45 ACP Tracer': ".45 ACP 예광탄",
            '"Nickname is not found"': "닉네임을 찾을 수 없음",
        })
        candidates = b.get_candidate_terms(
            ['Error: "Nickname is not found" after using .45 ACP Tracer ammo'],
            source_lang="en",
        )
        assert '.45 ACP Tracer' in candidates
        assert '"Nickname is not found"' in candidates

    def test_no_match_returns_empty(self):
        b = self._builder({"Ultimate": "궁극기"})
        candidates = b.get_candidate_terms(["completely unrelated text"], source_lang="en")
        assert candidates == {}

    def test_empty_terms_returns_empty(self):
        b = self._builder({})
        assert b.get_candidate_terms(["Ultimate skill"], source_lang="en") == {}

    def test_word_boundary_no_false_positive(self):
        """'key' should not match 'monkey'."""
        b = self._builder({"key": "키"})
        candidates = b.get_candidate_terms(["monkey around"], source_lang="en")
        assert "key" not in candidates


class TestFilterGlossaryByLlm:
    def _make_engine(self):
        from modules.translation_engine import TranslationEngine
        from prompts import PromptBuilder

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.openai = MagicMock()
        engine.openai_model = "gpt-5.2"
        engine.prompt_builder = PromptBuilder({}, "Test")
        return engine

    @staticmethod
    def _entries(n: int) -> list[GlossaryEntry]:
        return [
            GlossaryEntry(id=f"term{i}", en=f"term{i}", ko=f"용어{i}")
            for i in range(n)
        ]

    def test_below_threshold_skips_llm(self):
        """후보가 THRESHOLD 이하면 LLM 호출 없이 candidates 그대로 반환."""
        from models import GLOSSARY_FILTER_THRESHOLD

        engine = self._make_engine()
        small = self._entries(GLOSSARY_FILTER_THRESHOLD)
        result = engine._filter_glossary_by_llm(small, ["some text"])
        assert result == small
        engine.openai.beta.chat.completions.parse.assert_not_called()
        engine.openai.chat.completions.create.assert_not_called()

    def test_above_threshold_calls_llm_selected_ids(self):
        """후보가 THRESHOLD 초과면 LLM 호출."""
        from models import GLOSSARY_FILTER_THRESHOLD
        import modules.translation_engine as te_mod

        engine = self._make_engine()
        large = self._entries(GLOSSARY_FILTER_THRESHOLD + 5)

        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = '{"selected_ids": ["term0", "term1"]}'
        engine.openai.chat.completions.create.return_value = mock_completion

        with patch.object(te_mod, "PYDANTIC_AVAILABLE", False):
            result = engine._filter_glossary_by_llm(large, ["term0 term1 content"])

        assert [entry.id for entry in result] == ["term0", "term1"]

    def test_above_threshold_accepts_legacy_selected_keys(self):
        from models import GLOSSARY_FILTER_THRESHOLD
        import modules.translation_engine as te_mod

        engine = self._make_engine()
        large = self._entries(GLOSSARY_FILTER_THRESHOLD + 5)

        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = '{"selected_keys": ["term2"]}'
        engine.openai.chat.completions.create.return_value = mock_completion

        with patch.object(te_mod, "PYDANTIC_AVAILABLE", False):
            result = engine._filter_glossary_by_llm(large, ["term2 content"])

        assert [entry.id for entry in result] == ["term2"]

    def test_llm_error_falls_back_to_candidates(self):
        """LLM 오류 시 전체 candidates 반환 (graceful fallback)."""
        from models import GLOSSARY_FILTER_THRESHOLD
        import modules.translation_engine as te_mod

        engine = self._make_engine()
        large = self._entries(GLOSSARY_FILTER_THRESHOLD + 5)
        engine.openai.chat.completions.create.side_effect = RuntimeError("API error")

        with patch.object(te_mod, "PYDANTIC_AVAILABLE", False):
            result = engine._filter_glossary_by_llm(large, ["text"])

        assert result == large

    def test_empty_candidates_returns_empty(self):
        engine = self._make_engine()
        result = engine._filter_glossary_by_llm([], ["text"])
        assert result == []


class TestBuildGlossaryInstruction:
    def test_instruction_built_from_filtered_terms(self):
        from prompts import PromptBuilder

        b = PromptBuilder({"Ultimate": "궁극기", "Gadget": "가젯"}, "Heist")
        candidates = b.get_candidate_entries(["Use the Ultimate skill"], source_lang="en")
        instruction = b.build_glossary_instruction(
            ["Use the Ultimate skill"],
            source_lang="en",
            candidate_entries=candidates,
        )
        assert "en: Ultimate | ko: 궁극기" in instruction
        assert "Gadget" not in instruction

    def test_note_is_rendered_as_metadata(self):
        from prompts import PromptBuilder

        b = PromptBuilder({"Marksman": "저격수 (플레이어 롤/클래스)"}, "PBB")
        instruction = b.build_glossary_instruction(["Marksman role"], source_lang="en")
        assert "note: 플레이어 롤/클래스" in instruction
        assert "저격수 (플레이어 롤/클래스)" not in instruction

    def test_korean_source_orientation(self):
        from prompts import PromptBuilder

        b = PromptBuilder({"Marksman": "저격수"}, "PBB")
        instruction = b.build_glossary_instruction(["저격수 역할"], source_lang="ko")
        assert "ko: 저격수 | en: Marksman" in instruction


class TestIssueGlossaryScenarios:
    HEIST_TERMS = {
        "Ultimate": "궁극기",
        "Gadget": "가젯",
        "Locked & Loaded": "완전 무장 (스킬명. '킬 리로드'와 동일 영문)",
        "Locked & Loaded__2": "킬 리로드 (대체 번역)",
        "The Exchange": "환전소",
        "Marksman": "저격수 (플레이어 롤/클래스)",
        "Hideout": "하이드아웃",
    }

    def _builder(self):
        from prompts import PromptBuilder

        return PromptBuilder(self.HEIST_TERMS, "Heist")

    def test_only_matched_terms_in_candidates(self):
        b = self._builder()
        text = ["Player used Ultimate and visited The Exchange for a Gadget."]
        candidates = b.get_candidate_terms(text, source_lang="en")

        assert set(candidates.keys()) == {"Ultimate", "Gadget", "The Exchange"}
        assert "Marksman" not in candidates
        assert "Hideout" not in candidates

    def test_korean_text_matches_ko_value(self):
        b = self._builder()
        text = ["궁극기를 사용하여 환전소에서 아이템을 구매했습니다."]
        candidates = b.get_candidate_terms(text, source_lang="ko")

        assert "Ultimate" in candidates
        assert "The Exchange" in candidates
        assert "Gadget" not in candidates

    def test_duplicate_en_both_variants_matched(self):
        b = self._builder()
        text = ["Activate Locked & Loaded to reload."]
        candidates = b.get_candidate_terms(text, source_lang="en")

        assert "Locked & Loaded" in candidates
        assert "Locked & Loaded__2" in candidates

    def test_unrelated_issue_produces_empty_instruction(self):
        b = self._builder()
        instruction = b.build_glossary_instruction(
            ["Server crashed due to network timeout error."],
            source_lang="en",
        )
        assert instruction == ""
