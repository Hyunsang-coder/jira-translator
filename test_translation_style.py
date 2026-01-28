#!/usr/bin/env python3
"""
번역 스타일 테스트 스크립트.
P2-70735 테스트 티켓을 소스 티켓으로 리셋한 후 번역을 실행하고 결과를 출력합니다.

사용법:
    python test_translation_style.py SOURCE_TICKET

예시:
    python test_translation_style.py P2-12345
    python test_translation_style.py https://cloud.jira.krafton.com/browse/P2-12345
"""

import os
import re
import sys

from dotenv import load_dotenv

from jira_trans import JiraTicketTranslator, parse_issue_url


TEST_TICKET = "P2-70735"


def clean_summary(text: str) -> str:
    """Summary에서 번역문 제거 (Original / Translated 패턴)"""
    if not text:
        return ""
    return text.split(" / ")[0].strip()


def clean_text_field(text: str) -> str:
    """Description에서 {color:#4c9aff}...{color} 번역문 제거"""
    if not text:
        return ""
    cleaned = re.sub(r'\{color:#4c9aff\}.*?\{color\}', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def clean_steps(text: str, translator: JiraTicketTranslator) -> str:
    """Steps 필드에서 번역문 제거 (언어 감지 기반)"""
    if not text:
        return ""

    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) >= 2:
        first_lang = translator._detect_text_language(parts[0])
        second_lang = translator._detect_text_language(parts[1])
        if first_lang != "unknown" and second_lang != "unknown" and first_lang != second_lang:
            return parts[0]
    return text


def reset_test_ticket(translator: JiraTicketTranslator, source_key: str) -> bool:
    """소스 티켓 내용으로 테스트 티켓(P2-70735)을 리셋"""
    print(f"\n{'='*50}")
    print(f"1단계: 테스트 티켓 리셋")
    print(f"{'='*50}")
    print(f"소스: {source_key} → 타겟: {TEST_TICKET}")

    # 소스 티켓의 Steps 필드 결정
    if source_key.startswith("PUBG-") or source_key.startswith("PAYDAY-"):
        steps_field_source = "customfield_10237"
    else:
        steps_field_source = "customfield_10399"
    steps_field_target = "customfield_10399"  # P2-70735는 PBB

    fields_to_fetch = ["summary", "description", steps_field_source]

    try:
        source_data = translator.fetch_issue_fields(source_key, fields_to_fetch)
    except Exception as e:
        print(f"❌ 소스 티켓 가져오기 실패: {e}")
        return False

    if not source_data:
        print("❌ 소스 티켓 데이터 없음")
        return False

    # 데이터 정제
    clean_data = {
        "summary": clean_summary(source_data.get("summary", "")),
        "description": clean_text_field(source_data.get("description", "")),
    }

    raw_steps = source_data.get(steps_field_source)
    if raw_steps:
        clean_data[steps_field_target] = clean_steps(raw_steps, translator)

    print(f"  Summary: {clean_data['summary'][:50]}...")
    print(f"  Description: {len(clean_data['description'])} chars")
    if steps_field_target in clean_data:
        print(f"  Steps: {len(clean_data[steps_field_target])} chars")

    try:
        translator.update_issue_fields(TEST_TICKET, clean_data)
        print(f"✅ {TEST_TICKET} 리셋 완료")
        return True
    except Exception as e:
        print(f"❌ 리셋 실패: {e}")
        return False


def run_translation(translator: JiraTicketTranslator) -> dict | None:
    """테스트 티켓 번역 실행"""
    print(f"\n{'='*50}")
    print(f"2단계: 번역 실행")
    print(f"{'='*50}")
    print(f"타겟: {TEST_TICKET}")

    try:
        results_obj = translator.translate_issue(
            issue_key=TEST_TICKET,
            target_language=None,
            fields_to_translate=["summary", "description", "customfield_10399"],
            perform_update=True,
        )
        print(f"✅ 번역 및 업데이트 완료")
        return results_obj
    except Exception as e:
        print(f"❌ 번역 실패: {e}")
        return None


def show_results(results_obj: dict):
    """번역 결과 출력 및 스타일 체크"""
    print(f"\n{'='*50}")
    print(f"3단계: 결과 확인")
    print(f"{'='*50}")

    translations = results_obj.get("results") or {}

    if not translations:
        print("⚠️ 번역 결과 없음")
        return

    for field, content in translations.items():
        original = content.get("original", "")
        translated = content.get("translated", "")
        detected_lang = content.get("detected_lang", "")

        print(f"\n[{field}] (감지된 언어: {detected_lang})")
        print("-" * 40)
        print("원문:")
        print(original[:200] + "..." if len(original) > 200 else original)
        print("\n번역:")
        print(translated[:500] + "..." if len(translated) > 500 else translated)

        # 영→한 번역인 경우 습니다체 체크
        if detected_lang == "en" and field == "description":
            print("\n📝 스타일 체크 (습니다체):")
            if re.search(r'(합니다|됩니다|입니다|습니다)', translated):
                print("  ✅ '습니다'체 사용됨")
            else:
                print("  ⚠️ '습니다'체 미발견 - 확인 필요")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("❌ 소스 티켓을 지정해주세요.")
        sys.exit(1)

    source_input = sys.argv[1]

    # URL 또는 키 파싱
    try:
        _, source_key = parse_issue_url(source_input)
    except ValueError:
        source_key = source_input.upper()

    load_dotenv()

    jira_url = (os.getenv("JIRA_URL") or "https://cloud.jira.krafton.com").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    missing = [name for name, val in [
        ("JIRA_EMAIL", jira_email),
        ("JIRA_API_TOKEN", jira_api_token),
        ("OPENAI_API_KEY", openai_api_key),
    ] if not val]

    if missing:
        print(f"❌ 환경 변수 누락: {', '.join(missing)}")
        sys.exit(1)

    translator = JiraTicketTranslator(
        jira_url=jira_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )

    print(f"🧪 번역 스타일 테스트")
    print(f"소스 티켓: {source_key}")
    print(f"테스트 티켓: {TEST_TICKET}")

    # 1. 리셋
    if not reset_test_ticket(translator, source_key):
        sys.exit(1)

    # 2. 번역
    results = run_translation(translator)
    if not results:
        sys.exit(1)

    # 3. 결과 출력
    show_results(results)

    print(f"\n{'='*50}")
    print(f"🔗 결과 확인: https://cloud.jira.krafton.com/browse/{TEST_TICKET}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
