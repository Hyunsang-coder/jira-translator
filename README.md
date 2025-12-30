# Jira Ticket Translator

Jira 티켓을 한/영 양방향으로 자동 번역하는 AWS Lambda 기반 서버리스 애플리케이션입니다.

## 주요 기능

- ✅ **양방향 번역**: 한글 ↔ 영어 자동 감지 및 번역 (OpenAI GPT 모델 활용)
- ✅ **마크업 보존**: 이미지(`!...!`), 첨부파일(`[^...]`), 코드 블록(`{code}`), 링크 등 Jira 마크업 완벽 유지
- ✅ **프로젝트별 용어집**: `PUBG`, `PBB`, `HeistRoyale` 등 프로젝트별 맞춤 용어집 지원
- ✅ **자동 필드 매핑**: 이슈 키 접두사에 따른 재현 단계(Steps) 필드 자동 판별
- ✅ **REST API**: API Gateway/Lambda URL을 통한 HTTP 엔드포인트 제공
- ✅ **로컬 테스트**: 실제 배포 전 로컬 환경에서 번역 품질 및 로직 검증 가능

## 아키텍처

```
┌─────────────┐
│ API Gateway │ (또는 Lambda Function URL)
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────┐     ┌──────────┐
│   Lambda    │────▶│   Jira   │     │  OpenAI  │
│  Function   │     │   API    │     │   API    │
└─────────────┘     └──────────┘     └──────────┘
```

## 사전 요구사항

- Python 3.12+
- AWS CLI 및 SAM CLI 설치
- Jira API 토큰 (Atlassian 계정 설정에서 발급)
- OpenAI API 키

## 설치 및 설정

### 1. 저장소 클론 및 의존성 설치
```bash
git clone <repository-url>
cd jira-translator
pip install -r requirements.txt
```

### 2. 환경 변수 설정 (`.env`)
로컬 테스트를 위해 프로젝트 루트에 `.env` 파일을 생성합니다.
```env
JIRA_URL=https://cloud.jira.krafton.com
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o  # 권장 모델
```

## 프로젝트별 자동 매핑 가이드

이슈 키의 Prefix에 따라 시스템이 자동으로 설정을 변경합니다.

| 프로젝트 | 이슈 키 Prefix | 용어집 파일 | 재현 단계 필드 ID |
| :--- | :--- | :--- | :--- |
| **PUBG** | `PUBG-` | `glossaries/pubg_glossary.json` | `customfield_10237` |
| **HeistRoyale** | `PAYDAY-` | `glossaries/heist_glossary.json` | `customfield_10237` |
| **PBB** | `P2-` / 기타 | `glossaries/pbb_glossary.json` | `customfield_10399` |

## 배포 (AWS SAM)

### 1. 빌드 및 배포
```bash
sam build
sam deploy
```
*참고: 코드 수정 후에는 반드시 `sam build`를 먼저 수행해야 변경 사항이 반영됩니다.*

## API 사용법

### 번역 및 업데이트 요청
**POST** `/` (Lambda URL)
```json
{
  "issue_key": "PAYDAY-7",
  "update": true
}
```

**파라미터 상세:**
- `issue_key` (필수): 번역할 Jira 이슈 키 (예: `P2-70735`, `PAYDAY-5`)
- `update` (선택): `true`일 경우 번역 후 Jira 티켓을 실제로 업데이트합니다. (기본값: `false`)

## 로컬 개발 및 테스트

### 1. 통합 테스트 실행 (CLI)
```bash
python main.py
```
이슈 키를 입력받아 번역 결과를 터미널에 출력하고, 선택적으로 Jira 업데이트까지 수행합니다.

### 2. 유닛 테스트
```bash
# (권장) pytest
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

### 3. SAM 로컬 테스트 (2가지 방법)
SAM 템플릿(`template.yaml`)을 사용해 AWS 배포 전 로컬에서 Lambda/API Gateway 동작을 검증할 수 있습니다.


**AWS login 필요!!**
```bash
aws configure sso 
#configure 되어 있으면
aws sso login --profile AdministratorAccess-700388609892
``` 

#### 방법 A) `sam local invoke` (1회 실행)
- **장점**: 빠름, 반복 테스트에 좋음, 서버를 띄우지 않음
- **검증 범위**: Lambda 핸들러 로직(요청 파싱/번역 호출/응답 포맷)

1) 환경변수 파일 준비(로컬 전용, 절대 커밋하지 않기)

`env.json`:
```json
{
  "JiraTranslatorFunction": {
    "JIRA_URL": "your-jira-instance-url",
    "JIRA_EMAIL": "your-email@example.com",
    "JIRA_API_TOKEN": "your-jira-api-token",
    "OPENAI_API_KEY": "your-openai-api-key",
    "OPENAI_MODEL": "gpt-5.2"
  }
}
```

2) API Gateway Proxy 이벤트 파일 준비

`events/translate.json`:
```json
{
    "body": "{\"issue_key\":\"P2-70735\",\"update\":false}",
    "headers": {
        "Content-Type": "application/json"
    },
    "isBase64Encoded": false
}
```

3) 빌드 후 invoke 실행
```bash
sam build
sam local invoke JiraTranslatorFunction --event events/translate.json --env-vars env.json
```

#### 방법 B) `sam local start-api` (로컬 HTTP로 실제 호출)
- **장점**: API Gateway처럼 **실제 HTTP 요청**으로 검증(라우팅/Content-Type/body 파싱 포함)
- **검증 범위**: `/translate`, `/health` 엔드포인트 동작까지 end-to-end

```bash
sam build
sam local start-api --env-vars env.json
```

다른 터미널에서 호출:
```bash
curl -X POST "http://127.0.0.1:3000/translate" \
  -H "Content-Type: application/json" \
  -d '{"issue_key":"P2-70735","update":false}'
```

## 프로젝트 구조

```
jira-translator/
├── jira_trans.py          # Facade (진입점 호환성 유지)
├── handler.py             # Lambda 핸들러(진입점)
├── modules/               # 핵심 로직 모듈 (Refactored)
│   ├── jira_client.py     # Jira API 클라이언트
│   ├── translation_engine.py # OpenAI 번역 엔진
│   ├── formatting.py      # 포맷팅 및 마크업 처리
│   └── language.py        # 언어 감지 로직
├── glossaries/            # 프로젝트별 용어집
│   ├── heist_glossary.json
│   ├── pubg_glossary.json
│   └── pbb_glossary.json
├── prompts.py             # 프롬프트 빌더
├── models.py              # 데이터 모델
├── template.yaml          # SAM 템플릿
├── requirements.txt       # 의존성 목록
├── main.py                # 로컬 실행 스크립트
└── tests/                 # 테스트 케이스
```

---
*Last Updated: 2025-12-30*
