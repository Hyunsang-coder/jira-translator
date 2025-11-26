import os
import re
from dotenv import load_dotenv
from jira_trans import JiraTicketTranslator, parse_issue_url

def clean_summary(text):
    if not text:
        return ""
    # "Original / Translated" 패턴에서 앞부분(Original)만 추출
    return text.split(" / ")[0].strip()

def clean_text_field(text):
    """
    Description 등에서 {color:#4c9aff}...{color} 블록(번역문)을 제거
    """
    if not text:
        return ""
    # Jira Color 태그로 감싸진 번역문 제거
    # dotall=True(re.S)로 개행 포함 매칭
    cleaned = re.sub(r'\{color:#4c9aff\}.*?\{color\}', '', text, flags=re.DOTALL)
    
    # 테이블 내의 *Original/Translated* 패턴 처리
    # 예: *Original Text/Translated Text* -> Original Text
    # 너무 공격적인 정규식은 피하고, 명확한 패턴만 시도
    # (테이블 처리는 복잡하므로 여기서는 색상 태그 제거에 집중)
    
    # 연속된 공백 라인 정리 (번역문 제거로 생긴 빈 줄)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def clean_steps(text, translator):
    """
    Steps to Reproduce 필드에서 번역문 제거 (2단락 분리 감지)
    """
    if not text:
        return ""
    
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) >= 2:
        # 두 덩어리 이상일 때, 언어 감지를 통해 번역문(두 번째 덩어리)인지 확인
        # 보통 원문이 위에 있으므로 첫 번째를 원문으로 간주
        first_lang = translator._detect_text_language(parts[0])
        second_lang = translator._detect_text_language(parts[1])
        
        # 언어가 다르면(하나가 번역본이면) 첫 번째만 유지
        if first_lang != "unknown" and second_lang != "unknown" and first_lang != second_lang:
            return parts[0]
            
    return text

def main():
    load_dotenv()
    
    JIRA_URL = os.getenv("JIRA_URL", "https://cloud.jira.krafton.com").rstrip("/")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    if not all([JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY]):
        print("❌ 환경 변수 설정이 필요합니다 (.env 확인)")
        return

    # 타겟 티켓 (테스트용)
    TARGET_KEY = "P2-70735"
    
    print(f"🔧 Jira Test Ticket Resetter")
    print(f"Target Ticket: {TARGET_KEY}")
    print("-" * 30)

    # 1. 소스 티켓 입력
    source_input = input("원본 티켓 번호 또는 URL을 입력하세요: ").strip()
    if not source_input:
        print("❌ 티켓 번호를 입력해주세요.")
        return

    try:
        _, source_key = parse_issue_url(source_input)
    except ValueError:
        # URL 파싱 실패 시 입력값을 그대로 키로 사용
        source_key = source_input.upper()

    print(f"📥 소스 티켓({source_key}) 정보를 가져옵니다...")

    translator = JiraTicketTranslator(
        jira_url=JIRA_URL,
        email=JIRA_EMAIL,
        api_token=JIRA_API_TOKEN,
        openai_api_key=OPENAI_API_KEY
    )

    # 필드 결정
    steps_field_source = "customfield_10237" if source_key.startswith("PUBG-") else "customfield_10399"
    steps_field_target = "customfield_10399" # P2-70735는 PBB 프로젝트이므로 10399

    fields_to_fetch = ["summary", "description", steps_field_source]
    
    try:
        source_data = translator.fetch_issue_fields(source_key, fields_to_fetch)
    except Exception as e:
        print(f"❌ 소스 티켓 가져오기 실패: {e}")
        return

    if not source_data:
        print("❌ 소스 티켓 데이터를 찾을 수 없습니다.")
        return

    # 2. 데이터 정제 (번역문 제거)
    print("🧹 데이터 정제 중 (번역문 제거)...")
    
    raw_summary = source_data.get("summary", "")
    raw_description = source_data.get("description", "")
    raw_steps = source_data.get(steps_field_source, "")

    clean_data = {}
    
    # Summary
    clean_data["summary"] = clean_summary(raw_summary)
    
    # Description
    clean_data["description"] = clean_text_field(raw_description)
    
    # Steps (필드 ID 매핑 주의: 소스 필드 -> 타겟 필드)
    # clean_steps 내부에서 언어 감지 로직 사용
    clean_data[steps_field_target] = clean_steps(raw_steps, translator)

    print("\n📋 덮어쓸 내용 미리보기:")
    print(f"[Summary] {clean_data['summary']}")
    print(f"[Steps] {len(clean_data[steps_field_target])} chars")
    print(f"[Description] {len(clean_data['description'])} chars")
    
    # 3. 타겟 티켓 업데이트
    confirm = input(f"\n🚀 {TARGET_KEY} 티켓을 위 내용으로 덮어쓰시겠습니까? (y/n): ").lower()
    if confirm == "y":
        try:
            translator.update_issue_fields(TARGET_KEY, clean_data)
            print(f"✅ {TARGET_KEY} 업데이트 완료! (번역문이 있었다면 삭제되었습니다)")
        except Exception as e:
            print(f"❌ 업데이트 실패: {e}")
    else:
        print("취소되었습니다.")

if __name__ == "__main__":
    main()

