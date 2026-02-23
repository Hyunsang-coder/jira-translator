from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

try:
    # NOTE:
    # 로컬(mac)에서는 repo의 `package/`에 포함된 Linux용 pydantic_core 바이너리가
    # import 경로에 잡히면 `pydantic_core._pydantic_core` 로딩이 실패할 수 있습니다.
    # 이 경우에도 테스트/로컬 실행이 가능하도록 pydantic 의존을 optional로 둡니다.
    from pydantic import BaseModel  # type: ignore

    PYDANTIC_AVAILABLE = True
except Exception:  # pragma: no cover - 환경 의존(import/so 로딩 실패 포함)
    BaseModel = object  # type: ignore
    PYDANTIC_AVAILABLE = False


@dataclass
class TranslationChunk:
    id: str
    field: str
    original_text: str
    clean_text: str
    attachments: list[str]
    header: Optional[str] = None
    skip_translation: bool = False  # 번역 스킵 여부 (QA Environment 등)


class TranslationItem(BaseModel):
    id: str
    translated: str


class TranslationResponse(BaseModel):
    translations: list[TranslationItem]


@dataclass
class FieldTranslationJob:
    field: str
    original_value: str
    chunks: list[TranslationChunk]
    mode: str = "default"


class GlossarySelection(BaseModel):
    selected_keys: list[str]


GLOSSARY_FILTER_THRESHOLD = 30


