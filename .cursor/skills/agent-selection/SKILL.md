---
name: agent-selection
description: Selects the right HomeHub subagent profile, runs the 7-step work algorithm, and formats agent responses. Use when the task spans multiple domains, needs a specialized subagent, code review, architecture review, or a multi-step production fix.
---

# Agent Selection

## When to use

- Domain is unclear or spans backend, Django, SQL, bot, Docker, platform, or docs.
- User asks for code review, architecture review, or API documentation.
- Task needs a specialized subagent rather than general coding.

## Routing table

| Task | Profile | File |
|------|---------|------|
| Scoped backend path, bugfix | `backend-developer` | `agents/backend-developer` |
| Python runtime, packaging, typing, tests (not Django-specific) | `python-pro` | `agents/python-pro` |
| Django models, views, forms, ORM, admin, middleware | `django-developer` | `agents/django-developer` |
| SQL queries, indexes, migrations, data debugging | `sql-pro` | `agents/sql-pro` |
| Telegram bot on aiogram | `aiogram-engineer` | `agents/aiogram-engineer` |
| Dockerfile, image, container runtime | `docker-expert` | `agents/docker-expert` |
| Internal platform, deployment workflow, self-service infra | `platform-engineer` | `agents/platform-engineer` |
| Verify behavior from official documentation | `docs-researcher` | `agents/docs-researcher` |
| Consumer-facing API documentation | `api-documenter` | `agents/api-documenter` |
| Code health review | `code-reviewer` | `agents/code-reviewer` |
| Architecture review, system boundaries | `architect-reviewer` | `agents/architect-reviewer` |

If several profiles fit, pick the one that owns the **primary risk** (data → `sql-pro`, bot update path → `aiogram-engineer`, access control → `backend-developer`).

## Work algorithm

1. Determine agent role and task boundary.
2. Gather facts from code, schema, config, docs, or environment.
3. Separate facts from assumptions.
4. Find primary risk, defect, or design gap.
5. Propose or implement the smallest safe change.
6. Validate success path, failure path, and one external or integration boundary.
7. Return a concise report (see format below).

## Response format

Every agent response should include:

- exact scope analyzed or changed;
- confirmed problem, risk, or hypothesis with evidence;
- smallest safe fix or recommendation;
- what was validated directly;
- what still needs live environment verification;
- residual risk, compatibility notes, rollback notes, or next steps.

## Additional resources

- Full routing index: `AGENT_DEVELOPMENT_REQUIREMENTS.md`
- Agent profile format: `AGENTS.md`
- Component ownership map: `ARCHITECTURE.md` §13
