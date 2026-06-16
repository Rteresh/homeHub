---
name: homehub-context
description: Loads HomeHub domain context for feature work, MVP checks, and project conventions. Use when implementing HomeHub features, checking MVP compliance, or answering how things are done in this project.
---

# HomeHub Context

## What HomeHub is

Local home server: accept files/media via Telegram bot and web, store privately, browse via web UI. Smart devices are post-MVP.

## Key product rules

- Roles: `admin` sees all; `user` sees only own files.
- Auth and permissions enforced on backend, not UI alone.
- Files served through Django endpoints; real FS paths never exposed to clients.
- Telegram login via one-time link; bot accepts photo, video, GIF, documents.
- Standard Bot API file limit ~20 MB; larger files via web upload or Local Bot API.

## Architecture (MVP)

- Django monolith + separate aiogram bot process.
- Domain logic in service layer (`FileIngestionService`, `FileAccessService`, etc.).
- PostgreSQL for metadata; private local filesystem for files; `public_id` (UUID) for public URLs.
- Packages: `apps/accounts`, `apps/files`, `apps/web`, `bot/`, `homehub/`, `storage/`.

## Stack note

`PROJECT_SPEC.md` §8 mentions SQLite for MVP; the running project uses **PostgreSQL** per `README.md` and current code. Prefer README + code over outdated spec sections.

## Agent ownership (short)

See `ARCHITECTURE.md` §13: `django-developer` for Django layer, `backend-developer` for services/auth, `aiogram-engineer` for bot, `sql-pro` for data layer, `docker-expert` for containers.

## Reference docs (read when needed)

- Product requirements: `PROJECT_SPEC.md` (§5 functional, §6 non-functional, §9 MVP)
- Technical architecture: `ARCHITECTURE.md` (§2 decisions, §4 components, §7 services, §8 data flows)
- Human runbook (setup, commands, troubleshooting): `README.md`

Do not duplicate full spec text in responses — cite the relevant section or file.
