# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Jira Ticket Translator** is a serverless AWS Lambda application that automatically translates Jira tickets bidirectionally between Korean and English, with intelligent markup preservation and project-specific glossary support.

- **Runtime**: Python 3.12 on AWS Lambda
- **External APIs**: Jira REST API, OpenAI API (GPT models)
- **Infrastructure**: AWS SAM (Serverless Application Model)
- **Key Features**: Bidirectional translation, Jira markup preservation, project-specific glossaries, field mapping, REST API, local testing

## Core Commands

### Development Setup
```bash
pip install -r requirements.txt
```

### Local Testing & Validation

**Interactive Translation Testing (CLI)**
```bash
python main.py
# Prompts for issue key, shows translation preview, optionally updates Jira
```

**Unit Tests**
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

**SAM Local Invocation (1x Lambda execution)**
```bash
sam build
sam local invoke JiraTranslatorFunction --event events/translate.json --env-vars env.json
```

**SAM Local API Server (HTTP endpoint testing)**
```bash
sam build
sam local start-api --env-vars env.json
# In another terminal:
curl -X POST "http://127.0.0.1:3000/translate" \
  -H "Content-Type: application/json" \
  -d '{"issue_key":"P2-70735","update":false}'
```

### Deployment

**Using deploy script (recommended)**
```bash
./deploy.sh
# Sources .env, runs sam build, then sam deploy with parameter overrides
```

**Manual deployment**
```bash
sam build
sam deploy --parameter-overrides \
  "JiraUrl=\"$JIRA_URL\" \
   JiraEmail=\"$JIRA_EMAIL\" \
   JiraApiToken=\"$JIRA_API_TOKEN\" \
   OpenAIApiKey=\"$OPENAI_API_KEY\" \
   OpenAIModel=\"$OPENAI_MODEL\" \
   StageName=\"$STAGE_NAME\""
```

## Architecture & Key Components

### Module Structure

The codebase follows a **Facade + Components pattern** with backwards compatibility:

```
modules/
├── jira_client.py         # Jira API client (fetch fields, update issues, ADF normalization)
├── translation_engine.py  # OpenAI translation + glossary management
├── formatting.py          # Jira markup parsing & preservation (images, code, links, attachments)
└── language.py            # Language detection (Korean vs English)
```

**jira_trans.py** acts as a Facade that composes these modules and maintains backwards compatibility with existing code and tests.

### Critical Data Flow

1. **Issue Fetching** → `JiraClient.fetch_issue_fields()` retrieves raw + rendered fields from Jira API v2
2. **Language Detection** → `language.detect()` determines if text is Korean or English
3. **Translation** → `TranslationEngine.translate_text()` calls OpenAI while preserving markup
4. **Markup Preservation** → `formatting.extract_markup_blocks()` extracts/reinserts images, code blocks, links before/after translation
5. **Glossary Injection** → Project-specific terms (PUBG, HeistRoyale, PBB) from `glossaries/` are injected into prompts
6. **Jira Update** → `JiraClient.update_issue_fields()` sends `{"fields": {...}}` payload back to Jira

### Project-Specific Field Mapping

The system auto-detects projects by issue key prefix and applies project-specific settings:

| Project | Prefix | Glossary File | Steps Field |
|---------|--------|---------------|-------------|
| PUBG | `PUBG-` | `glossaries/pubg_glossary.json` | `customfield_10237` |
| HeistRoyale | `PAYDAY-` | `glossaries/heist_glossary.json` | `customfield_10237` |
| PBB (default) | `P2-`, other | `glossaries/pbb_glossary.json` | `customfield_10399` |

Mapping logic: `jira_trans.py:_determine_fields_and_glossary()` → returns `fields_to_translate` + `glossary_filename` based on prefix.

### Jira Markup Handling

Jira supports multiple markup syntaxes. The formatter preserves:
- **Images**: `!...!` blocks
- **Attachments**: `[^...]` syntax
- **Code blocks**: `{code}...{code}` (language-specific)
- **Links**: `[text|URL]` format
- **ADF (Atlassian Document Format)**: Complex nested structures from `renderedFields`

Key function: `formatting.extract_markup_blocks()` → splits text into `[markup_blocks, text_content]` → translates content only → `formatting.restore_markup()` reinserts blocks.

### Environment Configuration

**Local Development (.env)**
```
JIRA_URL=https://cloud.jira.krafton.com
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o  # or gpt-5.2
```

**Lambda Deployment (via template.yaml parameters)**
- Parameters are defined in `template.yaml` lines 15-48
- Applied via `sam deploy --parameter-overrides` or `deploy.sh`
- Environment variables injected at `template.yaml:81-87`

## Development Guidelines

### Code Changes

**Scope Minimization**: Modify only what's necessary for the feature/bug fix. Avoid unrelated refactoring or cleanup.

**Type & Data Models**: Update `models.py` first if changing data structures, then propagate to callers.

**Markup Regression Prevention**: Any changes to translation logic or field handling MUST be validated against existing tests in `tests/`:
- `test_formatting.py` - Image/code block preservation
- `test_batch_translation.py` - Multi-field translation
- `test_refined_logic.py` - Edge cases
- `test_ticket_type_logic.py` - Project-specific field mapping

**External API Error Handling**: Wrap Jira/OpenAI calls in try-catch blocks. Distinguish between:
- **Timeout errors** (retry logic)
- **Auth errors** (invalid token/credentials)
- **Rate limit errors** (backoff)
- **Data errors** (malformed response)

Return meaningful error messages to the user in Lambda responses.

### Testing Before Changes

1. Run unit tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`
2. Manual test with a real issue: `python main.py` (no update)
3. If touching markup or glossary logic, explicitly test edge cases

### Git Workflow

- Do NOT commit automatically
- Propose Conventional Commits format when changes are stable
- Never commit `.env`, `env.json`, or `package/` changes without explicit direction
- Recommend user reviews changes before pushing

## Known Constraints & Patterns

### Backwards Compatibility

`jira_trans.py` re-exports all public classes and maintains property-based access to internal components. Tests may import directly from `jira_trans`, not from individual modules.

### Glossary Loading

Glossary files are loaded relative to the `modules/` directory:
```python
base_dir = Path(__file__).resolve().parent.parent  # jira-translator/
glossary_path = base_dir / "glossaries" / filename
```

Glossaries are JSON with structure: `{"terms": {"korean": "english", ...}}`

### Pydantic Availability

The code conditionally uses Pydantic v2+ if available but falls back to dict-based models in `models.py`. Check `PYDANTIC_AVAILABLE` before using Pydantic-specific features.

### Lambda Context Limitations

- Timeout: 120 seconds (set in `template.yaml:79`)
- Memory: 1024 MB (set in `template.yaml:80`)
- No direct file system persistence between invocations
- Environment variables are immutable at runtime

## Testing Strategy

**Unit Tests** validate individual component logic (formatting, language detection, translation).

**Integration Tests** (via `main.py` or SAM local) validate the full pipeline:
1. Fetch issue from Jira
2. Detect language
3. Translate with glossary
4. Preserve markup
5. Build update payload
6. (Optionally) update Jira

**SAM Local Tests** verify:
- Lambda handler signature & event parsing (`sam local invoke`)
- API Gateway routing & CORS (`sam local start-api`)
- Environment variable injection

## Common Pitfalls

- **Broken Markup**: Changes to `formatting.py` can silently break image/code preservation. Always run `test_formatting.py`.
- **Field Mapping Errors**: Project detection relies on issue key prefix. Test with multiple project keys (PUBG-, PAYDAY-, P2-, etc.).
- **Glossary Not Loaded**: If custom glossary isn't used, check that the filename matches the project mapping and JSON structure is valid.
- **API Rate Limits**: OpenAI API can be rate-limited. Errors should be caught and reported clearly; SAM local tests may fail if quota is exhausted.
- **Jira Auth Failures**: Verify `.env` credentials match the Jira instance URL. API token expiry is a common issue.

## Directory Exclusions

Do NOT modify without explicit direction:
- `package/` - Dependency cache for SAM builds
- `.aws-sam/` - Build artifacts
- `node_modules/` (if present) - External dependencies

These are generated and should be rebuilt via `sam build`, not edited directly.
