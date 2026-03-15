# Job Autopilot v2

Career automation platform. Scrapes jobs, qualifies them against a resume using AI, generates tailored resumes and cover letters with dynamic project hooks.

## Current state

Working Python CLI (`main.py`) that scrapes LinkedIn → qualifies via Gemini → writes to Google Sheets. Uses flat files, no database, single-user only. After Phase 0, the original source lives in `legacy/` and `main.py` is a thin wrapper. Key existing modules:
- `legacy/linkedin_service.py` — LinkedIn API with cookie auth (reuse in Phase 4)
- `legacy/qualifiar.py` — Gemini scoring logic (reference for prompt design)
- `legacy/resume_processor.py` — PDF parse + cache as `resume.json`
- `legacy/sheets.py` — Google Sheets read/write (deprecated after Phase 5)
- `legacy/job_model.py` — job data model
- `legacy/config.py` / `config.example.py` — search params

## Target state

Multi-tenant FastAPI backend with Supabase (Postgres + pgvector + Storage). Gemini 2.0 Flash for orchestration, Gemini Embedding 2 for RAG. LaTeX pipeline for PDF resume generation. See `docs/plan.md` for the phased migration plan.

## Stack

- Python 3.11, FastAPI, Pydantic v2, `pydantic-settings`
- Supabase (`supabase-py`), pgvector (768-dim embeddings)
- `google-generativeai` SDK for Gemini
- `linkedin-api` for scraping (cookie auth, already working)
- LaTeX (`pdflatex`) for resume PDF rendering
- pytest for tests

## Architecture

```
app/
├── api/          # FastAPI routes + auth dependency
├── core/         # Supabase client, shared DB helpers
├── models/       # Pydantic schemas (request/response)
├── services/     # Business logic (one file per domain)
└── utils/        # LaTeX escaping, text chunking
sql/              # Supabase migration files
templates/        # LaTeX .tex templates with %%PLACEHOLDER%% markers
tests/
```

## Commands

- `source .venv/bin/activate`
- `pip install -r requirements.txt`
- `uvicorn app.main:app --reload` — run dev server
- `pytest tests/ -v` — run tests
- `python3 main.py` — run legacy CLI (still works during migration)

## Code style

- Async functions for anything touching Supabase or Gemini API
- Type hints everywhere, use `from __future__ import annotations`
- Pydantic models for all API boundaries
- `user_id` column in every user-facing table, RLS policies on all tables
- Environment variables via `pydantic-settings`, never hardcode secrets

## Important rules

- NEVER delete or break files in `legacy/` — the old CLI (`python3 main.py`) must keep working until Phase 7
- NEVER commit `.env`, `credentials/`, `resume.pdf`, or `resume.json`
- When creating Supabase tables, always include RLS policies
- Escape ALL text before injecting into LaTeX templates (10 special chars: `& % $ # _ { } ~ ^ \`)
- Embeddings are 768-dim (Gemini Embedding 2) — use `vector(768)` in schemas
- Job dedup: check URL first, then `lower(title)::lower(company)` hash
- Resume processing should run as a background task, not block the API response