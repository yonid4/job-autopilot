from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

_DB_PATH = Path(__file__).resolve().parents[2] / "data.db"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_JSON_COLS = {"embedding", "parsed_json", "technologies", "strengths", "gaps"}
_BOOL_COLS = {"is_active"}


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    con = _connect()
    con.executescript(_SCHEMA_PATH.read_text())
    con.commit()
    con.close()


def _dumps(v):
    return json.dumps(v) if v is not None else None


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for col in _JSON_COLS:
        if col in d and d[col] is not None:
            d[col] = json.loads(d[col])
    for col in _BOOL_COLS:
        if col in d:
            d[col] = bool(d[col])
    return d


def _title_company(title: str, company: str) -> str:
    return f"{title.lower()}::{company.lower()}"


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom else 0.0


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def find_job_by_url(url: str) -> dict | None:
    con = _connect()
    row = con.execute("SELECT * FROM jobs WHERE url = ? LIMIT 1", (url,)).fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def find_job_by_title_company(title: str, company: str) -> dict | None:
    key = _title_company(title, company)
    con = _connect()
    row = con.execute(
        "SELECT * FROM jobs WHERE title_company = ? LIMIT 1", (key,)
    ).fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def upsert_job(data: dict) -> dict:
    data = dict(data)
    if "id" not in data:
        data["id"] = str(uuid4())
    data["title_company"] = _title_company(data["title"], data["company"])
    data["embedding"] = _dumps(data.get("embedding"))

    con = _connect()
    with con:
        con.execute(
            """
            INSERT INTO jobs (id, url, title, company, description, salary,
                              job_level, title_company, embedding)
            VALUES (:id, :url, :title, :company, :description, :salary,
                    :job_level, :title_company, :embedding)
            ON CONFLICT(url) DO UPDATE SET
                title         = excluded.title,
                company       = excluded.company,
                description   = excluded.description,
                salary        = excluded.salary,
                job_level     = excluded.job_level,
                title_company = excluded.title_company,
                embedding     = excluded.embedding
            """,
            data,
        )
    row = con.execute("SELECT * FROM jobs WHERE url = ?", (data["url"],)).fetchone()
    con.close()
    return _row_to_dict(row)


def list_jobs(limit: int = 50) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT id, url, title, company, description, salary, job_level, created_at"
        " FROM jobs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

def get_active_resume(user_id: str) -> dict | None:
    con = _connect()
    row = con.execute(
        "SELECT * FROM resumes WHERE user_id = ? AND is_active = 1 LIMIT 1",
        (user_id,),
    ).fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def insert_resume(data: dict) -> dict:
    data = dict(data)
    if "id" not in data:
        data["id"] = str(uuid4())
    data["is_active"] = 1 if data.get("is_active") else 0
    data["parsed_json"] = _dumps(data.get("parsed_json"))

    con = _connect()
    with con:
        con.execute(
            """
            INSERT INTO resumes (id, user_id, label, storage_path, parsed_json, is_active)
            VALUES (:id, :user_id, :label, :storage_path, :parsed_json, :is_active)
            """,
            data,
        )
    row = con.execute("SELECT * FROM resumes WHERE id = ?", (data["id"],)).fetchone()
    con.close()
    return _row_to_dict(row)


def set_active_resume(user_id: str, resume_id: str) -> None:
    con = _connect()
    with con:
        con.execute(
            "UPDATE resumes SET is_active = 0 WHERE user_id = ? AND id != ?",
            (user_id, resume_id),
        )
        con.execute(
            "UPDATE resumes SET is_active = 1 WHERE id = ?",
            (resume_id,),
        )
    con.close()


def list_resumes(user_id: str) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT id, user_id, label, storage_path, is_active"
        " FROM resumes WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    con.close()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Resume chunks
# ---------------------------------------------------------------------------

def insert_resume_chunks(chunks: list[dict]) -> None:
    if not chunks:
        return
    rows = [
        {
            "id": str(uuid4()),
            "user_id": c["user_id"],
            "resume_id": c["resume_id"],
            "chunk_index": c["chunk_index"],
            "section": c.get("section"),
            "content": c["content"],
            "embedding": _dumps(c.get("embedding")),
        }
        for c in chunks
    ]
    con = _connect()
    with con:
        con.executemany(
            """
            INSERT INTO resume_chunks
                (id, user_id, resume_id, chunk_index, section, content, embedding)
            VALUES (:id, :user_id, :resume_id, :chunk_index, :section, :content, :embedding)
            """,
            rows,
        )
    con.close()


def delete_resume_chunks(resume_id: str) -> None:
    con = _connect()
    with con:
        con.execute("DELETE FROM resume_chunks WHERE resume_id = ?", (resume_id,))
    con.close()


def get_resume_chunks(resume_id: str) -> list[str]:
    """Return all chunk content strings for a resume, ordered by chunk_index."""
    con = _connect()
    rows = con.execute(
        "SELECT content FROM resume_chunks WHERE resume_id = ? ORDER BY chunk_index",
        (resume_id,),
    ).fetchall()
    con.close()
    return [r["content"] for r in rows]


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------

def get_resume_by_id(resume_id: str) -> dict | None:
    con = _connect()
    row = con.execute(
        "SELECT * FROM resumes WHERE id = ? LIMIT 1", (resume_id,)
    ).fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def match_resume_chunks(
    user_id: str, resume_id: str, embedding: list[float], limit: int = 10
) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT id, chunk_index, section, content, embedding"
        " FROM resume_chunks"
        " WHERE user_id = ? AND resume_id = ? AND embedding IS NOT NULL",
        (user_id, resume_id),
    ).fetchall()
    con.close()

    scored = []
    for r in rows:
        d = dict(r)
        vec = json.loads(d["embedding"])
        scored.append(
            {
                "id": d["id"],
                "chunk_index": d["chunk_index"],
                "section": d["section"],
                "content": d["content"],
                "similarity": _cosine(embedding, vec),
            }
        )
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def insert_project(data: dict) -> dict:
    data = dict(data)
    if "id" not in data:
        data["id"] = str(uuid4())
    data["technologies"] = _dumps(data.get("technologies"))
    data["embedding"] = _dumps(data.get("embedding"))

    con = _connect()
    with con:
        con.execute(
            """
            INSERT INTO user_projects
                (id, user_id, name, description, technologies, url, embedding)
            VALUES (:id, :user_id, :name, :description, :technologies, :url, :embedding)
            """,
            data,
        )
    row = con.execute(
        "SELECT * FROM user_projects WHERE id = ?", (data["id"],)
    ).fetchone()
    con.close()
    return _row_to_dict(row)


def get_projects(user_id: str) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT id, user_id, name, description, technologies, url, created_at"
        " FROM user_projects WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    con.close()
    return [_row_to_dict(r) for r in rows]


def match_best_project(user_id: str, embedding: list[float]) -> dict | None:
    con = _connect()
    rows = con.execute(
        "SELECT id, name, description, technologies, url, embedding"
        " FROM user_projects"
        " WHERE user_id = ? AND embedding IS NOT NULL",
        (user_id,),
    ).fetchall()
    con.close()

    best: dict | None = None
    best_score = -1.0
    for r in rows:
        d = dict(r)
        vec = json.loads(d["embedding"])
        score = _cosine(embedding, vec)
        if score > best_score:
            best_score = score
            best = {
                "id": d["id"],
                "name": d["name"],
                "description": d["description"],
                "technologies": json.loads(d["technologies"]) if d["technologies"] else [],
                "url": d["url"],
                "similarity": score,
            }
    return best


# ---------------------------------------------------------------------------
# Jobs (remaining helpers)
# ---------------------------------------------------------------------------

def get_job_by_id(job_id: str) -> dict | None:
    con = _connect()
    row = con.execute(
        "SELECT * FROM jobs WHERE id = ? LIMIT 1", (job_id,)
    ).fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def cache_job_embedding(job_id: str, embedding: list[float]) -> None:
    con = _connect()
    with con:
        con.execute(
            "UPDATE jobs SET embedding = ? WHERE id = ?",
            (_dumps(embedding), job_id),
        )
    con.close()


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def upsert_application(data: dict) -> dict:
    data = dict(data)
    if "id" not in data:
        data["id"] = str(uuid4())
    data["strengths"] = _dumps(data.get("strengths"))
    data["gaps"] = _dumps(data.get("gaps"))
    now = datetime.now(timezone.utc).isoformat()
    data.setdefault("created_at", now)
    data["updated_at"] = now

    con = _connect()
    with con:
        con.execute(
            """
            INSERT INTO applications
                (id, user_id, job_id, resume_id, status, fit_score,
                 strengths, gaps, summary_text, cover_letter, pdf_path,
                 hook_project_id, created_at, updated_at)
            VALUES
                (:id, :user_id, :job_id, :resume_id, :status, :fit_score,
                 :strengths, :gaps, :summary_text, :cover_letter, :pdf_path,
                 :hook_project_id, :created_at, :updated_at)
            ON CONFLICT(user_id, job_id) DO UPDATE SET
                resume_id       = excluded.resume_id,
                status          = excluded.status,
                fit_score       = COALESCE(excluded.fit_score,       applications.fit_score),
                strengths       = COALESCE(excluded.strengths,       applications.strengths),
                gaps            = COALESCE(excluded.gaps,            applications.gaps),
                summary_text    = COALESCE(excluded.summary_text,    applications.summary_text),
                cover_letter    = COALESCE(excluded.cover_letter,    applications.cover_letter),
                pdf_path        = COALESCE(excluded.pdf_path,        applications.pdf_path),
                hook_project_id = COALESCE(excluded.hook_project_id, applications.hook_project_id),
                updated_at      = excluded.updated_at
            """,
            {
                "id": data["id"],
                "user_id": data["user_id"],
                "job_id": data["job_id"],
                "resume_id": data.get("resume_id"),
                "status": data.get("status", "not_applied"),
                "fit_score": data.get("fit_score"),
                "strengths": data["strengths"],
                "gaps": data["gaps"],
                "summary_text": data.get("summary_text"),
                "cover_letter": data.get("cover_letter"),
                "pdf_path": data.get("pdf_path"),
                "hook_project_id": data.get("hook_project_id"),
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
            },
        )
    row = con.execute(
        "SELECT * FROM applications WHERE user_id = ? AND job_id = ?",
        (data["user_id"], data["job_id"]),
    ).fetchone()
    con.close()
    return _row_to_dict(row)


def get_applications(user_id: str, status: str | None = None) -> list[dict]:
    con = _connect()
    if status:
        rows = con.execute(
            "SELECT * FROM applications WHERE user_id = ? AND status = ?"
            " ORDER BY created_at DESC",
            (user_id, status),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    con.close()
    return [_row_to_dict(r) for r in rows]


def update_application_status(
    application_id: str, user_id: str, status: str
) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    con = _connect()
    with con:
        con.execute(
            "UPDATE applications SET status = ?, updated_at = ?"
            " WHERE id = ? AND user_id = ?",
            (status, now, application_id, user_id),
        )
    row = con.execute(
        "SELECT * FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    con.close()
    return _row_to_dict(row) if row else None
