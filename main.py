import json
import os

from dotenv import load_dotenv

from jira_trans import JiraTicketTranslator


def run_end_to_end_translation():
    """
    JiraTicketTranslator 전체 파이프라인을 로컬에서 검증하기 위한 스크립트.
    - Jira 이슈 조회 → 번역(OpenAI) → payload 생성 → 업데이트 여부 확인까지 수행한다.
    """
    load_dotenv()

    jira_url = (os.getenv("JIRA_URL") or "https://cloud.jira.krafton.com").rstrip("/")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_api_token = os.getenv("JIRA_API_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    missing = [name for name, value in [
        ("JIRA_EMAIL", jira_email),
        ("JIRA_API_TOKEN", jira_api_token),
        ("OPENAI_API_KEY", openai_api_key),
    ] if not value]
    if missing:
        print(f"❌ 환경 변수가 부족합니다: {', '.join(missing)}")
        return

    issue_key = input("번역/업데이트할 Jira 이슈 키를 입력하세요 (예: P2-70735): ").strip()
    if not issue_key:
        print("❌ 이슈 키가 비어 있어. 기본값 P2-70735를 사용합니다.")
        issue_key = "P2-70735"

    translator = JiraTicketTranslator(
        jira_url=jira_url,
        email=jira_email,
        api_token=jira_api_token,
        openai_api_key=openai_api_key,
    )

    print(f"➡️  {issue_key} 번역 중...")
    results_obj = translator.translate_issue(
        issue_key=issue_key,
        target_language=None,
        fields_to_translate=["summary", "description", "customfield_10399"],
        perform_update=False,
    )

    translations = results_obj.get("results") or {}
    payload = results_obj.get("update_payload") or translator.build_field_update_payload(translations)

    if not translations:
        print("⚠️ 번역 결과가 없습니다.")
        return

    print("\n=== 번역 결과 요약 ===")
    for field, content in translations.items():
        print(f"\n[{field}]")
        print("- 원문:")
        print(content.get("original", ""))
        print("\n- 번역:")
        print(content.get("translated", ""))

    print("\n=== Jira 업데이트 payload 미리보기 ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    summary_value = payload.get("summary", "")
    if summary_value:
        print(f"\nSummary 최종 길이: {len(summary_value)} (<= 255)")

    confirm = input("\n실제로 Jira 이슈를 업데이트할까요? [y/N]: ").strip().lower()
    if confirm != "y":
        print("취소되었습니다. Jira 이슈는 변경되지 않았습니다.")
        return

    if not payload:
        print("ℹ️ 업데이트할 필드가 없습니다.")
        return

    translator.update_issue_fields(issue_key, payload)


if __name__ == "__main__":
    run_end_to_end_translation()
