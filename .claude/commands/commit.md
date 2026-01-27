# Commit with AI-generated message

Use haiku model for fast, cost-effective commit message generation.

## Context
See `_context.md` for project structure.

## Pre-conditions (Auto-check)

Before committing, automatically verify:

1. **If `glossaries/*.json` changed** → Run `/validate-glossary` first
2. **If `modules/` or `prompts.py` changed** → Recommend `/test` first
3. **If tests fail** → Warn user, ask whether to proceed

## Instructions

1. Run `git status` and `git diff --staged` to see what's being committed
2. If nothing is staged, run `git diff` to see unstaged changes and ask user what to stage
3. **Check pre-conditions above** and run dependent skills if needed
4. Generate a conventional commit message based on the changes:
   - Use format: `type(scope): description`
   - Types: feat, fix, refactor, docs, test, chore, style, perf
   - Keep description under 72 characters
   - Add body if changes are complex
5. Show the proposed commit message to user
6. Execute `git commit -m "message"` with the generated message
7. Add `Co-Authored-By: Claude Haiku <noreply@anthropic.com>` to the commit

## Model

Use haiku model for this task.

## Example output

```
feat(prompts): improve Korean observation verb translation

- Changed '확인하다' translation from 'confirm' to 'observe'
- Better reflects QA context for reproduction steps

Co-Authored-By: Claude Haiku <noreply@anthropic.com>
```

## Chained Skills
- `/validate-glossary` - Called if glossary files changed
- `/test` - Recommended if core modules changed
