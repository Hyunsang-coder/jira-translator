# Progress Log

- 2025-11-11: Updated `test.py` to prompt for a Jira issue URL, fetch summary/description/customfield_10399 via Jira REST API v2, and translate fields with LangChain v1-compatible updates.
- 2025-11-17: Added `jira_trans_v2.py` implementing a LangChain v1 + LangGraph StateGraph-based Jira translation workflow with clearly separated nodes (fetch, detect language, translate, build payload, update).
- 2025-11-18: Added TDD coverage plus batch translation pipeline in `jira_trans.py` that reduces OpenAI calls to a single JSON-based request while preserving existing bilingual formatting, now with retry + per-field fallback and missing-chunk handling.
