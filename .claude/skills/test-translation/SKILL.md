---
name: test-translation
description: Jira 티켓 번역 품질을 읽기 전용으로 검증합니다. 기존 번역을 제거한 원문 기반으로 번역을 다시 실행하고, 원문/순수 번역/최종 바이링구얼(실제 티켓 포맷) 3종 비교 HTML 리포트를 생성합니다. Jira 티켓 수정은 절대 하지 않습니다.
---

# Test Translation Skill

이 스킬은 `translation_style_report.py`를 실행해 번역 품질 리포트를 만든다.

## 실행

```bash
python translation_style_report.py $ARGS
```

옵션 예시:

```bash
python translation_style_report.py PAYDAY-104 --target-language Korean
python translation_style_report.py https://cloud.jira.krafton.com/browse/P2-70735 --output /tmp/p2-70735-preview.html
```

## 기대 동작

1. Jira 티켓을 읽기 전용으로 가져온다 (`summary`, `description`, steps).
2. 기존 번역 흔적을 제거해 원문만 추출한다.
3. 실제 번역 파이프라인과 같은 규칙으로 번역한다.
4. HTML 리포트를 생성한다:
   - Source (Extracted)
   - Translated (Raw Assembly)
   - Bilingual (Final Ticket Format)
5. 로컬 브라우저로 리포트를 연다.

## 출력/확인 포인트

- 기본 리포트 경로: `/tmp/{issue_key}_translation.html`
- 모델: `OPENAI_MODEL`이 없으면 기본 `gpt-5.2`
- Jira 티켓 업데이트는 수행하지 않는다 (read-only)
