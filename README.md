# Jira Ticket Translator

Jira 티켓을 한/영 양방향으로 자동 번역하는 AWS Lambda 기반 서버리스 애플리케이션입니다.

## 주요 기능

- ✅ **양방향 번역**: 한글 ↔ 영어 자동 감지 및 번역
- ✅ **마크업 보존**: 이미지, 첨부파일, 코드 블록 등 Jira 마크업 유지
- ✅ **용어집 지원**: 프로젝트별 용어집을 통한 일관된 번역
- ✅ **REST API**: API Gateway를 통한 HTTP 엔드포인트 제공
- ✅ **로컬 테스트**: 로컬 환경에서 전체 파이프라인 테스트 가능

## 아키텍처

```
┌─────────────┐
│ API Gateway │
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
- AWS 계정 및 적절한 권한
- Jira API 토큰
- OpenAI API 키

## 설치

### 1. 저장소 클론

```bash
git clone <repository-url>
cd jira-translator
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

또는 `uv` 사용:

```bash
uv pip install -r requirements.txt
```

### 3. 환경 변수 설정

`.env` 파일 생성:

```bash
JIRA_URL=https://your-jira-instance.com
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-5.2
```

## 배포

### 1. AWS 자격 증명 설정

`samconfig.toml`에 AWS 프로필 설정:

```toml
[default.global.parameters]
region = "ap-northeast-2"
profile = "your-aws-profile"
```

### 2. SAM 템플릿 파라미터 설정

`template.yaml` 또는 `samconfig.toml`에서 다음 파라미터 설정:

- `JiraUrl`: Jira 인스턴스 URL
- `JiraEmail`: Jira 계정 이메일
- `JiraApiToken`: Jira API 토큰
- `OpenAIApiKey`: OpenAI API 키
- `OpenAIModel`: 사용할 OpenAI 모델 (기본값: `gpt-5.2`)
- `StageName`: 배포 스테이지 (`dev`, `staging`, `prod`)

### 3. 빌드 및 배포

```bash
# 빌드
sam build

# 배포
sam deploy
```

배포 후 출력되는 API Gateway URL을 확인하세요.

## API 사용법

### 번역 엔드포인트

**POST** `/translate`

```json
{
  "issue_key": "PROJ-123",
  "target_language": null,
  "fields_to_translate": ["summary", "description"],
  "perform_update": false
}
```

**GET** `/translate?issue_key=PROJ-123&fields=summary,description`

**파라미터:**
- `issue_key` (필수): 번역할 Jira 이슈 키
- `target_language` (선택): `"ko"` 또는 `"en"`. `null`이면 자동 감지
- `fields_to_translate` (선택): 번역할 필드 목록 (기본값: `["summary", "description"]`)
- `perform_update` (선택): 번역 후 Jira에 자동 업데이트 여부 (기본값: `false`)

**응답:**

```json
{
  "issue_key": "PROJ-123",
  "results": {
    "summary": {
      "original": "Original text",
      "translated": "번역된 텍스트"
    },
    "description": {
      "original": "...",
      "translated": "..."
    }
  },
  "update_payload": {
    "summary": "번역된 텍스트",
    "description": "..."
  }
}
```

### 헬스체크 엔드포인트

**GET** `/health`

Lambda 함수 상태 확인용 엔드포인트입니다.

## 로컬 개발

### 로컬 테스트 실행

```bash
python main.py
```

이 스크립트는:
1. Jira 이슈 조회
2. OpenAI를 통한 번역
3. 번역 결과 미리보기
4. 사용자 확인 후 Jira 업데이트

### 로컬 Lambda 테스트

```bash
sam local invoke JiraTranslatorFunction --event events/event.json
```

## 프로젝트 구조

```
jira-translator/
├── jira_trans.py          # 핵심 번역 로직
├── main.py                # 로컬 테스트 스크립트
├── template.yaml          # SAM 템플릿
├── samconfig.toml        # SAM 배포 설정
├── requirements.txt       # Python 의존성
├── pbb_glossary.json      # PUBG 용어집
├── pubg_glossary.json     # PUBG 용어집
└── tests/                 # 테스트 파일
```

## 주요 기능 상세

### 마크업 보존

Jira 마크업 형식을 자동으로 감지하고 보존합니다:

- 이미지: `!image.png!`, `!image.png|thumbnail!`
- 첨부파일: `[^attachment.pdf]`
- 코드 블록: `{code}`, `{code:python}`
- 링크: `[링크|URL]`

### 용어집 지원

프로젝트별 용어집 파일(`*_glossary.json`)을 지원하여 일관된 번역을 제공합니다.

### 섹션 헤더 처리

Description 필드의 섹션 헤더를 자동으로 인식하고 처리합니다:

- `Observed:`, `Expected:`, `Note:`, `Video:` 등

## 환경 변수

| 변수명 | 설명 | 필수 |
|--------|------|------|
| `JIRA_URL` | Jira 인스턴스 URL | ✅ |
| `JIRA_EMAIL` | Jira 계정 이메일 | ✅ |
| `JIRA_API_TOKEN` | Jira API 토큰 | ✅ |
| `OPENAI_API_KEY` | OpenAI API 키 | ✅ |
| `OPENAI_MODEL` | 사용할 OpenAI 모델 | ❌ (기본값: `gpt-5.2`) |

## 트러블슈팅

### CloudWatch Logs Role 오류

API Gateway 배포 시 "CloudWatch Logs role ARN must be set" 오류가 발생하면:

1. `template.yaml`에 `ApiGatewayCloudWatchRole`과 `ApiGatewayAccount` 리소스가 포함되어 있는지 확인
2. 스택을 삭제 후 재배포:

```bash
aws cloudformation delete-stack --stack-name jira-translator
sam build
sam deploy
```

### 다른 AWS 계정으로 배포

`samconfig.toml`에서 프로필 변경:

```toml
[default.global.parameters]
profile = "your-target-profile"
```

SSO 사용 시:

```bash
aws sso login --profile your-target-profile
```

## 라이선스

[라이선스 정보 추가]

## 기여

[기여 가이드라인 추가]

