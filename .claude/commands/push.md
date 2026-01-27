# Push and Deploy

Push to remote and deploy to AWS Lambda via SAM.

## Context
See `_context.md` for project structure.

## Pre-conditions (Auto-check)

Before pushing, automatically verify:

1. **If uncommitted changes exist** → Ask user to run `/commit` first or stash
2. **If tests haven't passed recently** → Recommend `/test` before deploy
3. **If glossaries changed since last commit** → Run `/validate-glossary`

## Instructions

1. Run `git status` to verify working directory state
2. **Check pre-conditions above**
3. Run `git push` to push commits to remote
4. If push fails (e.g., no upstream), set upstream with `git push -u origin <branch>`
5. After successful push, run the deployment pipeline:
   ```bash
   sam build
   ```
6. If build succeeds, deploy:
   ```bash
   ./deploy.sh
   ```
7. Report deployment status to user

## Prerequisites

- AWS CLI configured with SSO login
- `.env` file with required variables (JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, OPENAI_API_KEY, OPENAI_MODEL)

## Error Handling

- If `git push` fails: Show error and ask user how to proceed
- If `sam build` fails: Show build errors and stop (don't deploy)
- If `./deploy.sh` fails: Show deployment errors

## Success Output

Report:
- Git push status (branch, remote)
- SAM build status
- Deployment status (stack name, API endpoint if available)

## Chained Skills
- `/commit` - Called if uncommitted changes exist
- `/test` - Recommended before deploy
- `/validate-glossary` - Called if glossary files changed
