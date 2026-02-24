# Session Handoff

> Generated: 2026-02-23 오늘
> Branch: agent

## 작업 요약

Glossary 파일이 수천 개 규모로 커질 경우를 대비해 2단계 필터 구조를 설계하는 아키텍처 논의를 진행했다. 코드 변경은 없었고, `agent` 브랜치를 생성하고 구현 전략을 확정했다.

## 현재 상태

### 변경된 파일
없음 (아직 코드 변경 없음, 브랜치만 생성)

### 커밋 이력 (이번 세션)
없음

## 미완료 작업

- [ ] 새 Glossary 포맷 지원: `data["glossary"]` (카테고리별 리스트, ko/en/note) → flat dict 변환 로직 추가
- [ ] `prompts.py` `build_glossary_instruction` → 1단계 후보 추출 메서드 분리 (`get_candidate_terms`)
- [ ] `translation_engine.py` → 2단계 LLM 필터 메서드 추가 (`_filter_glossary_by_llm`)
- [ ] `models.py` → `GlossarySelection(BaseModel)` 추가 (selected_keys: list[str])
- [ ] 임계값 상수 정의 (`GLOSSARY_FILTER_THRESHOLD = 30`)
- [ ] 단위 테스트 작성

## 핵심 결정 사항

- **2단계 필터 구조 채택**: 1단계 string match로 전체 용어를 후보로 압축 → 2단계 gpt-5.2로 실제 필요 용어만 정제. LangChain/Anthropic SDK는 Lambda 패키지 크기 및 복잡도 증가로 불채택.
- **모델 고정 gpt-5.2**: 2단계 필터도 gpt-5.2 사용 (mini 불가, 사용자 지시)
- **한국어 1단계 오탐 허용**: 형태소 분석기 미도입, 1단계는 관대하게 잡고 2단계 LLM이 정제하는 방식 채택
- **순차 실행**: async 전환 없이 순차 구현 후 성능 이슈 발생 시 병렬화 검토
- **새 Glossary 포맷**: `/Users/joo/Desktop/PUBG_WORK/ingame_string/heist_royale_glossary.json` 형태 (카테고리 + note 포함) 지원 예정

## 주의사항

- 현재 `_load_glossary_terms`는 `data.get("terms")` flat dict만 읽음 → 새 포맷 대응 필요
- 현재 `build_glossary_instruction`이 이미 1단계 역할을 함 → 메서드 분리만 하면 됨 (로직 재작성 불필요)
- 2단계 필터는 후보가 `GLOSSARY_FILTER_THRESHOLD` 이하일 때 스킵 (불필요한 API 호출 방지)
- 기존 테스트(`test_formatting.py`, `test_batch_translation.py` 등) 회귀 방지 필수

## 핵심 파일

- `modules/translation_engine.py` — glossary 로드 + 번역 엔진 (주 수정 대상)
- `prompts.py` — `build_glossary_instruction` 1단계 로직 (메서드 분리 대상)
- `models.py` — `GlossarySelection` 모델 추가 대상
- `glossaries/heist_glossary.json` — 현재 flat 포맷 (새 포맷으로 교체 예정)
- `/Users/joo/Desktop/PUBG_WORK/ingame_string/heist_royale_glossary.json` — 새 포맷 참고 파일

## 다음 세션 가이드

1. `models.py` 먼저 열어서 `GlossarySelection` Pydantic 모델 추가
2. `translation_engine.py`의 `_load_glossary_terms`에 새 포맷(카테고리 리스트) 파싱 추가
3. `prompts.py`의 `build_glossary_instruction`에서 후보 추출 로직을 `get_candidate_terms`로 분리
4. `translation_engine.py`에 `_filter_glossary_by_llm` 메서드 추가 (gpt-5.2, Structured Output)
5. 기존 테스트 실행 후 회귀 확인: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
