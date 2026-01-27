# Project Context (Shared)

This file provides shared context for all skills in this project.

## Project Type
- AWS Lambda serverless application (Python 3.12)
- SAM (Serverless Application Model) deployment
- Jira + OpenAI API integration

## Key Paths
- **Source**: `jira_trans.py`, `handler.py`, `modules/`
- **Tests**: `tests/`
- **Glossaries**: `glossaries/*.json`
- **Config**: `.env`, `env.json`, `template.yaml`

## Commands Reference
| Task | Command |
|------|---------|
| Test | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` |
| Build | `sam build` |
| Deploy | `./deploy.sh` |
| Local test | `python main.py` |

## Critical Files (Always test after changes)
- `modules/formatting.py` - Markup preservation
- `modules/translation_engine.py` - Translation logic
- `modules/language.py` - Language detection
- `prompts.py` - Translation prompts
- `glossaries/*.json` - Term dictionaries

## Skill Dependencies
```
commit ─────────────────────────────► git commit
   │
   └─► (recommend) test ◄─── should run before commit

push ───► git push ───► sam build ───► deploy.sh
   │
   └─► (require) commit first if uncommitted changes

validate-glossary ◄─── run before commit if glossaries changed
```
