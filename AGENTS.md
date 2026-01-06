## AGENTS.md (Cursor)

이 문서는 Cursor 에이전트가 이 저장소에서 작업할 때 따라야 할 **프로젝트별 규칙/흐름/주의사항**을 정의합니다.

## Spec-driven development

- 이 저장소에 `trd.md`(또는 `specs/`)가 존재하고, 사용자 요청이 해당 스펙과 충돌한다면 **먼저 사용자에게 스펙 변경 의사부터 확인**하세요.
- 사용자가 “스펙은 그대로, 구현만 바꾸자”가 아니라 “요구사항이 바뀐 것”이라면, **우선 `trd.md`를 업데이트**하는 것을 제안한 뒤 작업을 진행하세요.
- 참고: 현재 기준(2026-01-02) 워크스페이스에는 `trd.md` / `specs/`가 없을 수 있습니다. 없다면 이 규칙은 “향후 추가될 때”에만 적용합니다.

## 프로젝트 개요

- **목적**: Jira 티켓을 한/영 양방향으로 번역하고(언어 자동 감지), 선택적으로 Jira 티켓을 업데이트하는 서버리스 앱
- **런타임/배포**: AWS Lambda (Python 3.12) + AWS SAM (`template.yaml`, `samconfig.toml`)
- **외부 의존**: Jira REST API, OpenAI API

## 주요 엔트리/디렉터리

- `handler.py`: Lambda 핸들러 진입점
- `main.py`: 로컬 CLI 실행(통합 테스트용)
- `modules/`: 핵심 로직
  - `jira_client.py`: Jira API 연동
  - `translation_engine.py`: 번역 엔진(OpenAI)
  - `formatting.py`: Jira 마크업 보존/포맷팅
  - `language.py`: 언어 감지
- `glossaries/`: 프로젝트별 용어집 JSON
- `tests/`: pytest 테스트
- `template.yaml`: SAM 리소스 정의(함수/환경변수/엔드포인트)

## 절대 수정/커밋하지 말아야 할 것

- **비밀정보**: `.env`, `env.json` (이미 `.gitignore`에 포함). 로그/코드/문서에 키를 복사하지 마세요.
- **벤더 디렉터리**: `package/`, `wheelhouse/`는 배포/번들링을 위한 의존성 스냅샷 성격일 수 있습니다. 특별한 지시가 없으면 **직접 수정하지 마세요**.
- **빌드 산출물**: `.aws-sam/` 등 생성물은 원칙적으로 수정 대상이 아닙니다.

## 개발/검증 커맨드 (로컬)

### 의존성 설치

- 기본:
  - `pip install -r requirements.txt`

### 로컬 실행(간이 통합 테스트)

- `python main.py`

### 테스트

- 빠른 실행(권장):
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`

## SAM 로컬 테스트

- 1회 실행(서버 불필요):
  - `sam build`
  - `sam local invoke JiraTranslatorFunction --event events/translate.json --env-vars env.json`

- 로컬 API 서버(`sam local start-api`)는 장시간 실행됩니다.
  - 에이전트는 **사용자 확인 없이 서버를 띄우지 마세요**.
  - 필요하면 “왜 필요한지/어떤 포트인지/종료 방법”을 함께 안내하세요.

## 배포

- 권장: `./deploy.sh` (내부에서 `.env` 로드 후 `sam build`, `sam deploy` 수행)
- 배포 전: `template.yaml`, `samconfig.toml` 변경 시 파라미터/리전/프로파일 영향 범위를 설명하세요.

## 코드 변경 가이드

- **변경 최소화**: 목표 기능/버그에 필요한 범위만 수정
- **타입/모델**: 데이터 구조는 `models.py`를 우선 정리하고, 호출부가 이를 사용하도록 유지
- **포맷 보존**: Jira 마크업/코드블록/첨부/링크 보존 로직은 회귀가 잦으니 관련 테스트(`tests/`)를 반드시 확인
- **에러 처리**: 외부 API(Jira/OpenAI) 호출은 실패 케이스(타임아웃/권한/레이트리밋)를 고려해 사용자에게 의미 있는 에러를 반환/로그

## Git 워크플로

- 에이전트는 **자동으로 커밋/푸시하지 않습니다**.
- 변경이 안정적이면 사용자에게 “커밋을 고려해보세요”와 함께 Conventional Commits 형식의 메시지를 제안하세요.