#!/bin/bash
# deploy.sh - Jira Translator 배포 스크립트
# 환경 변수를 사용하여 AWS SAM 배포를 수행합니다.

set -e  # 에러 발생 시 스크립트 중단

# 색상 출력
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Jira Translator 배포 시작${NC}"

# .env 파일 로드
if [ -f .env ]; then
    echo -e "${YELLOW}📄 .env 파일 로드 중...${NC}"
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
else
    echo -e "${RED}❌ .env 파일이 없습니다!${NC}"
    echo "   .env 파일을 생성하고 필요한 환경 변수를 설정하세요."
    exit 1
fi

# 필수 환경 변수 확인
MISSING_VARS=()

if [ -z "$JIRA_API_TOKEN" ]; then
    MISSING_VARS+=("JIRA_API_TOKEN")
fi

if [ -z "$OPENAI_API_KEY" ]; then
    MISSING_VARS+=("OPENAI_API_KEY")
fi

if [ ! -z "$MISSING_VARS" ]; then
    echo -e "${RED}❌ 필수 환경 변수가 설정되지 않았습니다:${NC}"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    exit 1
fi

# 기본값 설정
JIRA_URL=${JIRA_URL:-"https://krafton.atlassian.net"}
JIRA_EMAIL=${JIRA_EMAIL:-"hyunsang_joo@pubg.com"}
OPENAI_MODEL=${OPENAI_MODEL:-"gpt-5.2"}
STAGE_NAME=${STAGE_NAME:-"prod"}

echo -e "${GREEN}✅ 환경 변수 확인 완료${NC}"
echo "   JIRA_URL: $JIRA_URL"
echo "   JIRA_EMAIL: $JIRA_EMAIL"
echo "   OPENAI_MODEL: $OPENAI_MODEL"
echo "   STAGE_NAME: $STAGE_NAME"

# 빌드
echo -e "${YELLOW}🔨 Building...${NC}"
sam build

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 빌드 실패${NC}"
    exit 1
fi

# 배포
echo -e "${YELLOW}🚀 Deploying...${NC}"
sam deploy --parameter-overrides \
  "JiraUrl=\"$JIRA_URL\" \
   JiraEmail=\"$JIRA_EMAIL\" \
   JiraApiToken=\"$JIRA_API_TOKEN\" \
   OpenAIApiKey=\"$OPENAI_API_KEY\" \
   OpenAIModel=\"$OPENAI_MODEL\" \
   StageName=\"$STAGE_NAME\""

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 배포 완료!${NC}"

    # 배포된 Lambda 버전 정보 출력
    echo -e "${YELLOW}📋 배포된 Lambda 정보:${NC}"
    FUNCTION_NAME="jira-translator-${STAGE_NAME}"
    aws lambda get-function --function-name "$FUNCTION_NAME" \
        --query 'Configuration.{LastModified:LastModified,CodeSha256:CodeSha256}' \
        --output table 2>/dev/null || echo "   (Lambda 정보 조회 실패 - AWS CLI 설정 확인)"

    # Git commit 정보
    echo -e "${YELLOW}📋 Git 커밋 정보:${NC}"
    echo "   $(git log -1 --format='%h %s' 2>/dev/null || echo 'Git 정보 없음')"
else
    echo -e "${RED}❌ 배포 실패${NC}"
    exit 1
fi

