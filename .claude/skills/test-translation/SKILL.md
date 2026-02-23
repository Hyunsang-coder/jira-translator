---
name: test-translation
description: 기존 번역된 Jira 티켓을 읽기 전용으로 가져와 새로 번역한 결과를 원문과 나란히 비교하는 HTML 리포트를 생성합니다. Jira 티켓은 절대 수정하지 않습니다.
---

# Test Translation Skill

이슈 키 또는 Jira URL을 받아 해당 티켓의 원문을 가져와서
번역 엔진을 돌린 뒤, **원문 vs 새 번역**을 나란히 보여주는 HTML 리포트를 생성하고 브라우저로 엽니다.

**Jira 티켓은 절대 수정하지 않습니다. 읽기 전용.**

---

## Step 1: 이슈 키 확인

args에서 이슈 키 또는 URL을 파싱한다.
- URL 형식: `https://cloud.jira.krafton.com/browse/PAYDAY-104` → `PAYDAY-104` 추출
- 이슈 키 형식: `PAYDAY-104`, `P2-70735`, `PUBG-1234` 그대로 사용
- args가 없으면 AskUserQuestion으로 요청

## Step 2: 티켓 원문 가져오기 (읽기 전용)

```python
import os, re, sys
from dotenv import load_dotenv

# load_dotenv()를 인자 없이 쓰면 heredoc/stdin 실행 시 find_dotenv() AssertionError 발생
# 반드시 절대 경로로 명시할 것
load_dotenv('/Users/joo/Documents/GitHub/jira-translator/.env')
sys.path.insert(0, '/Users/joo/Documents/GitHub/jira-translator')

from modules.jira_client import JiraClient

client = JiraClient(
    jira_url=os.environ['JIRA_URL'],
    email=os.environ['JIRA_EMAIL'],
    api_token=os.environ['JIRA_API_TOKEN']
)

# steps 필드를 명시적으로 포함해야 함 — 기본값은 summary/description만 가져옴
fields = client.fetch_issue_fields(
    issue_key,
    fields_to_fetch=["summary", "description", "customfield_10237", "customfield_10399"]
)
```

가져올 필드: `summary`, `description`, steps 필드 (프로젝트별 자동 감지)

## Step 3: 이미 번역된 필드에서 원문만 추출

이미 바이링구얼 포맷인 경우 원문 라인만 추출:
- `{color:#4c9aff}...{color}` 블록 제거 (번역 부분)
- 나머지가 원문

원문이 영어인 경우(EN→KO 티켓)는 영어 원문 그대로 사용.

```python
def extract_source_text(text: str) -> str:
    """바이링구얼 텍스트에서 {color} 번역 블록 제거."""
    cleaned = re.sub(r'\{color:#4c9aff\}.*?\{color\}', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

def extract_korean_only(text: str) -> str:
    """
    steps처럼 '한국어 단락 + 빈 줄 + 영어 단락' 구조일 때 한국어 단락만 반환.
    한글 문자가 하나라도 있는 단락만 유지.
    """
    text = extract_source_text(text)
    paragraphs = re.split(r'\n{2,}', text)
    korean_paragraphs = []
    for para in paragraphs:
        if any(re.search(r'[가-힣]', line) for line in para.strip().splitlines()):
            korean_paragraphs.append(para.strip())
    return '\n\n'.join(korean_paragraphs).strip()
```

- `description` → `extract_source_text` 사용
- `steps` → `extract_korean_only` 사용 (한국어+영어 혼합 단락 구조이므로)

## Step 4: 번역 실행

프로젝트 prefix로 glossary 자동 선택:
- `PAYDAY-` → `heist_glossary.json` / `Heist Royale`
- `PUBG-` → `pubg_glossary.json` / `PUBG`
- `P2-`, 기타 → `pbb_glossary.json` / `PBB`

```python
from modules.translation_engine import TranslationEngine

engine = TranslationEngine(
    openai_api_key=os.environ['OPENAI_API_KEY'],
    model=os.environ.get('OPENAI_MODEL', 'gpt-4o')
)
engine.load_glossary(glossary_file, glossary_name)

# translate_field 사용 (마크업 보존 포함)
# 반드시 client.fetch_issue_fields()로 가져온 실제 문자열을 사용할 것
# Python 문자열 리터럴에 하드코딩하면 \! 이스케이프 오염 발생
translated = engine.translate_field(source_text)
```

## Step 5: HTML 리포트 생성 후 브라우저로 열기

`/tmp/{issue_key}_translation.html` 경로에 HTML 파일 생성 후 `open` 명령으로 브라우저에서 열기.

HTML 구조:
- 상단: 이슈 키, Jira 링크, 생성 시각
- 필드별 2컬럼 테이블: 왼쪽 원문 / 오른쪽 번역
- 원문 배경: 연한 노랑 `#fffbe6`
- 번역 배경: 연한 파랑 `#e8f4fd`
- Jira 마크업은 그대로 표시 (pre-wrap)

```python
from datetime import datetime

def build_html(issue_key, jira_url, fields_data):
    """
    fields_data: [{"field": "summary", "source": "...", "translated": "..."}, ...]
    """
    jira_link = f"{jira_url}/browse/{issue_key}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows_html = ""
    for f in fields_data:
        if not f["source"]:
            continue
        rows_html += f"""
        <section>
          <h2>{f['field']}</h2>
          <div class="compare">
            <div class="source">
              <div class="label">원문</div>
              <pre>{f['source']}</pre>
            </div>
            <div class="translated">
              <div class="label">번역</div>
              <pre>{f['translated']}</pre>
            </div>
          </div>
        </section>
        """

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{issue_key} 번역 비교</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; padding: 24px; background: #f5f5f5; color: #333; }}
  header {{ margin-bottom: 24px; }}
  header h1 {{ margin: 0 0 4px; font-size: 1.4rem; }}
  header a {{ color: #0052cc; font-size: 0.9rem; }}
  header time {{ color: #888; font-size: 0.85rem; margin-left: 12px; }}
  section {{ background: white; border-radius: 8px; padding: 20px;
             margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  section h2 {{ margin: 0 0 16px; font-size: 1rem; color: #555;
                text-transform: uppercase; letter-spacing: .05em; }}
  .compare {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .source, .translated {{ border-radius: 6px; padding: 14px; }}
  .source {{ background: #fffbe6; border: 1px solid #ffe58f; }}
  .translated {{ background: #e8f4fd; border: 1px solid #91caff; }}
  .label {{ font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
            letter-spacing: .06em; margin-bottom: 8px; }}
  .source .label {{ color: #b8860b; }}
  .translated .label {{ color: #0958d9; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: break-word;
         font-family: inherit; font-size: 0.9rem; line-height: 1.6; }}
</style>
</head>
<body>
<header>
  <h1>🔍 {issue_key} 번역 비교</h1>
  <a href="{jira_link}" target="_blank">{jira_link}</a>
  <time>{now}</time>
</header>
{rows_html}
</body>
</html>"""


output_path = f"/tmp/{issue_key}_translation.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(build_html(issue_key, os.environ['JIRA_URL'], fields_data))

import subprocess
subprocess.run(["open", output_path])
print(f"✅ 리포트 생성: {output_path}")
```

## 주의사항

- **Jira 티켓 수정 절대 금지** — `client.update_issue_fields()` 호출 금지
- 이미 번역된 티켓이어도 원문 추출 후 재번역하여 품질 비교 가능
- 바이링구얼 포맷(원문+파란색 번역)은 의도된 동작 — 이 스킬은 새 번역 품질 검토 전용
- HTML에서 `<`, `>`, `&` 문자는 `html.escape()`로 이스케이프할 것
