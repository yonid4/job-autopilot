# Job Autopilot v2 — Migration Plan

Step-by-step migration from CLI script to multi-tenant FastAPI + Supabase platform.
Each phase is self-contained: it can be tested and verified before moving on.

---

## ~~Phase 0: Organize existing codebase~~ ✅ DONE

**Goal:** Move the existing flat-file project into a clean structure without breaking anything. The old CLI (`python3 main.py`) must still work after this phase.

**Completed:** All source files moved to `legacy/` package, imports fixed, root `main.py` is a thin wrapper, `app/` skeleton created, `.gitignore` updated.

---

## ~~Phase 1: Foundation (database + project structure)~~ ✅ DONE

**Goal:** Supabase schema exists, FastAPI skeleton runs, no business logic yet.

**Completed:** `app/config.py` (Pydantic Settings), `app/main.py` (`/health` endpoint), `sql/001_schema.sql` (all tables + RLS + IVFFlat indexes + RPCs), `requirements.txt` updated, `.env.example` updated. Schema applied in Supabase.

---

## ~~Phase 2: Database layer + auth~~ ✅ DONE

**Goal:** Supabase client wrapper works, JWT auth extracts user_id, Pydantic schemas defined.

**Completed:**
- `app/core/database.py` — Supabase client singleton + all DB helpers
- `app/api/auth.py` — JWT dependency (verifies Supabase HS256 token, returns `user_id`); requires `SUPABASE_JWT_SECRET` (Dashboard → Settings → API → JWT Secret)
- `app/models/schemas.py` — all Pydantic models
- `tests/test_schemas.py` — 10/10 passing

---

## ~~Phase 3: Gemini service + resume pipeline~~ ✅ DONE

**Goal:** Can upload a resume PDF, parse it with Gemini, chunk it, embed it, store in Supabase.

**Completed:**
- `app/services/gemini_service.py` — `embed_text`, `embed_query`, `qualify_job`, `generate_summary`, `generate_cover_letter` with key rotation
- `app/services/resume_service.py` — `parse_resume_pdf` (Gemini vision), `chunk_parsed_resume`, `process_resume` (full pipeline)
- `app/api/routes.py` — `POST /api/v1/resumes/upload` (BackgroundTask), `GET /api/v1/resumes`
- `app/main.py` — router wired in
- `tests/conftest.py` — env stubs so unit tests work without .env
- `tests/test_resume_service.py` — 14/14 passing (chunking logic)

**Verify:** Upload a resume via the API. Check Supabase: `resumes` table has a row, `resume_chunks` table has embedded chunks.

---

## Phase 4: Job ingestion + project hooks

**Goal:** Can ingest jobs (with dedup), add projects, and find the best project hook for a job.

Tasks:
1. Create `app/services/job_service.py`:
   - `ingest_job_by_url(url)` → checks Supabase for existing, scrapes if new (reuse `linkedin_service.py` logic), embeds description, stores
   - `ingest_job_manual(job_data)` → same flow for manually provided jobs
   - Wire in the existing `linkedin_service.py` for the actual scraping (import and adapt, don't rewrite)
2. Add routes to `app/api/routes.py`:
   - `POST /api/v1/jobs/ingest` — ingest by URL or manual
   - `GET /api/v1/jobs` — list recent jobs
   - `POST /api/v1/projects` — create project (embed on creation)
   - `GET /api/v1/projects` — list user's projects
3. Write tests: `tests/test_job_service.py` (test dedup logic with mocked DB)

**Verify:** Ingest a job via API. Ingest same job again — should return `is_new: false`. Create a project, verify embedding is stored.

---

## ~~Phase 5: Tailoring engine (the core)~~ ✅ DONE

**Goal:** The `/tailor` endpoints work end-to-end: job + resume → score + summary + cover letter + hook.

**Completed:**
- `app/services/tailoring_engine.py` — three public functions sharing common internal helpers:
  - `tailor_resume` — embed JD → fetch chunks → qualify_job → generate_summary → upsert application
  - `tailor_cover_letter` — embed JD → fetch chunks → match_best_project → generate_cover_letter → upsert application
  - `tailor_full` — single embedding pass doing both (most efficient)
- `app/models/schemas.py` — 6 tailoring schemas (`TailorResumeRequest/Result`, `TailorCoverLetterRequest/Result`, `TailorFullRequest/Result`) + `ApplicationOut` + `ApplicationStatusUpdate`
- `app/api/routes.py` — `POST /api/v1/tailor/resume`, `POST /api/v1/tailor/cover-letter`, `POST /api/v1/tailor/full`, `GET /api/v1/applications`, `PATCH /api/v1/applications/{id}/status`
- `app/core/database.py` — `get_job_by_id`, `get_resume_by_id`, `match_resume_chunks`, `match_best_project`, `upsert_application`, `get_applications`, `update_application_status`
- `sql/002_set_active_resume.sql` — atomic resume activation RPC
- `tests/test_tailoring.py` — 12/12 passing

**Security fixes applied (code review):**
- JWT: algorithm allowlist enforced before branching (`HS256`, `ES256`, `RS256` only)
- Resume activation made atomic via `set_active_resume` RPC
- Upload capped at 10 MB
- `list_jobs` limit capped at 200 via `Query(ge=1, le=200)`
- `ApplicationStatusUpdate.status` validated as `Literal[...]`
- `updated_at` uses `datetime.now(timezone.utc)` not string `"now()"`
- `qualify_job` uses `model_validate_json` instead of bare `json.loads`

**Verify:** Call `/tailor/resume` or `/tailor/full` with a job_id. Check `applications` table for score, summary, cover letter, and matched project.

---

## Phase 6: LaTeX pipeline

**Goal:** Can generate a tailored resume PDF from a LaTeX template with AI-injected content.

Tasks:
1. Create `app/services/latex_service.py`:
   - `escape_latex(text)` — escape all 10 special characters
   - `inject_into_template(template_text, replacements)` — swap `%%PLACEHOLDER%%` markers
   - `render_tailored_pdf(user_id, resume, summary_text, job_title, company)` — compile with pdflatex, upload to Supabase Storage
2. Create `templates/resume_template.tex` — LaTeX template with `%%NAME%%`, `%%PROFESSIONAL_SUMMARY%%`, etc.
3. Wire PDF generation into the tailoring engine (`generate_pdf=True` flag in `TailorRequest`)
4. Add pdflatex to system dependencies (document in README)
5. Write tests: `tests/test_latex.py` (test escaping, test placeholder injection)

**Verify:** Call `/tailor` with `generate_pdf: true`. Download the PDF from Supabase Storage. Verify it renders correctly with the AI-generated summary.

---

## Phase 7: Polish + deprecate legacy

**Goal:** Clean up, add error handling, deprecate the old CLI path.

Tasks:
1. Add proper error responses and HTTP status codes to all routes
2. Add rate limiting or basic throttling on Gemini calls
3. Add CORS configuration for frontend origins
4. Update `README.md` to document the v2 API
5. Add a deprecation notice to the old `main.py` CLI pointing to the API
6. Final pass: remove any unused imports, add docstrings, verify all RLS policies

**Verify:** Full API walkthrough: upload resume → add projects → ingest job → tailor → download PDF. All steps work.