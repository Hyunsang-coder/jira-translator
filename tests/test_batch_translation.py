import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = lambda *args, **kwargs: SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda *a, **k: None)
        )
    )
    sys.modules["openai"] = openai_stub

from jira_trans import JiraTicketTranslator, TranslationChunk


def _build_translator(monkeypatch):
    # Avoid hitting real OpenAI during tests by stubbing after instantiation.
    translator = JiraTicketTranslator(
        jira_url="https://example.atlassian.net",
        email="bot@example.com",
        api_token="token",
        openai_api_key="sk-test",
    )
    translator.openai = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda *args, **kwargs: None  # will be replaced per test
            )
        )
    )
    translator.openai_model = "gpt-test"
    return translator


def test_call_openai_batch_parses_response(monkeypatch):
    translator = _build_translator(monkeypatch)

    calls = []

    def fake_create(model, messages):
        calls.append({"model": model, "messages": messages})
        payload = {
            "translations": [
                {"id": "summary", "translated": "요약 번역"},
                {"id": "description__section_0", "translated": "관찰 번역"},
            ]
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload))
                )
            ]
        )

    translator.openai.chat.completions.create = fake_create

    chunks = [
        TranslationChunk(
            id="summary",
            field="summary",
            original_text="Login fails",
            clean_text="Login fails",
            attachments=[],
            header=None,
        ),
        TranslationChunk(
            id="description__section_0",
            field="description",
            original_text="Observed content",
            clean_text="Observed content",
            attachments=[],
            header="Observed",
        ),
    ]

    result = translator._call_openai_batch(chunks, target_language="Korean")

    assert len(calls) == 1, "OpenAI API should be called exactly once"
    assert result == {
        "summary": "요약 번역",
        "description__section_0": "관찰 번역",
    }
    # ensure prompt includes both chunk texts
    rendered_prompt = calls[0]["messages"][-1]["content"]
    assert "Login fails" in rendered_prompt
    assert "Observed content" in rendered_prompt


def test_translate_issue_batches_all_fields(monkeypatch):
    translator = _build_translator(monkeypatch)

    issue_fields = {
        "summary": "[Client] Crash occurs",
        "description": "Observed:\nApp crashes.\n\nExpected:\nApp should not crash.",
        "customfield_10399": "1. Open client\n2. Click start",
    }

    def fake_fetch(issue_key, fields):
        return issue_fields

    translator.fetch_issue_fields = fake_fetch

    call_count = {"value": 0}

    def fake_batch(chunks, target_language):
        call_count["value"] += 1
        assert target_language == "Korean"
        assert {chunk.id for chunk in chunks} == {
            "summary",
            "description__section_0",
            "description__section_1",
            "customfield_10399",
        }
        return {chunk.id: f"KR:{chunk.clean_text}" for chunk in chunks}

    translator._call_openai_batch = fake_batch

    results_obj = translator.translate_issue(
        issue_key="BUG-1",
        target_language="Korean",
        fields_to_translate=[
            "summary",
            "description",
            "customfield_10399",
        ],
    )

    assert call_count["value"] == 1, "All chunks should be translated in one batch"

    translations = results_obj["results"]

    assert translations["summary"]["translated"] == "KR:Crash occurs"

    observed_block = translator._format_bilingual_block(
        "App crashes.", "KR:App crashes.", header="Observed"
    )
    expected_block = translator._format_bilingual_block(
        "App should not crash.", "KR:App should not crash.", header="Expected"
    )
    expected_description = "\n\n".join([observed_block, expected_block]).strip()
    assert translations["description"]["translated"] == expected_description

    assert translations["customfield_10399"]["translated"] == "KR:1. Open client\n2. Click start"


def test_call_openai_batch_fills_missing_chunks(monkeypatch):
    translator = _build_translator(monkeypatch)

    chunks = [
        TranslationChunk(
            id="summary",
            field="summary",
            original_text="Login fails",
            clean_text="Login fails",
            attachments=[],
        ),
        TranslationChunk(
            id="description__section_0",
            field="description",
            original_text="Observed content",
            clean_text="Observed content",
            attachments=[],
            header="Observed",
        ),
    ]

    def fake_once(self, _chunks, _target):
        return {"summary": "요약 번역"}

    fallback_calls = []

    def fake_translate_chunk_text(self, chunk, target_language):
        fallback_calls.append(chunk.id)
        return "관찰 번역"

    translator._call_openai_batch_once = types.MethodType(fake_once, translator)
    translator._translate_chunk_text = types.MethodType(fake_translate_chunk_text, translator)

    result = translator._call_openai_batch(chunks, target_language="Korean")

    assert result["summary"] == "요약 번역"
    assert result["description__section_0"] == "관찰 번역"
    assert fallback_calls == ["description__section_0"]


def test_translate_issue_fallbacks_when_batch_fails(monkeypatch):
    translator = _build_translator(monkeypatch)

    issue_fields = {
        "summary": "[Client] Crash occurs",
        "description": "Observed:\nApp crashes.\n\nExpected:\nApp should not crash.",
        "customfield_10399": "1. Open client\n2. Click start",
    }

    translator.fetch_issue_fields = lambda issue_key, fields: issue_fields

    def fake_batch(self, chunks, target_language, retries=2):
        raise ValueError("batch boom")

    translator._call_openai_batch = types.MethodType(fake_batch, translator)
    translator.translate_text = lambda text, target_language="Korean": f"KR:{text}"

    results_obj = translator.translate_issue(
        issue_key="BUG-2",
        target_language="Korean",
        fields_to_translate=[
            "summary",
            "description",
            "customfield_10399",
        ],
    )

    translations = results_obj["results"]

    assert translations["summary"]["translated"] == "KR:Crash occurs"

    observed_block = translator._format_bilingual_block(
        "App crashes.", "KR:App crashes.", header="Observed"
    )
    expected_block = translator._format_bilingual_block(
        "App should not crash.", "KR:App should not crash.", header="Expected"
    )
    expected_description = "\n\n".join([observed_block, expected_block]).strip()
    assert translations["description"]["translated"] == expected_description

    assert translations["customfield_10399"]["translated"] == "KR:1. Open client\n2. Click start"

