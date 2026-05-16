from __future__ import annotations

import json
from datetime import datetime, timezone

from google.genai import types

from app.core import database
from app.services.gemini_service import embed_text, generate_with_rotation, _GENERATION_MODEL


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

_PARSE_SYSTEM_PROMPT = """You are an expert resume parser.

Extract structured data from the resume and return it as JSON with this exact schema:
{
  "name": string,
  "email": string | null,
  "phone": string | null,
  "summary": string | null,
  "skills": [string, ...],
  "experience": [
    {
      "title": string,
      "company": string,
      "duration": string,
      "description": string
    }
  ],
  "education": [
    {
      "degree": string,
      "field": string,
      "school": string,
      "graduation_year": string | null
    }
  ],
  "projects": [
    {
      "name": string,
      "description": string,
      "technologies": [string, ...]
    }
  ],
  "certifications": [string, ...]
}

Return ONLY valid JSON, no markdown code fences."""


def parse_resume_pdf(pdf_bytes: bytes) -> dict:
    """Parse a resume PDF using Gemini vision. Returns structured JSON dict."""
    raw = generate_with_rotation(
        model=_GENERATION_MODEL,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            system_instruction=_PARSE_SYSTEM_PROMPT,
        ),
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            "Extract all information from this resume.",
        ],
    )
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_parsed_resume(parsed: dict) -> list[dict]:
    """Convert a parsed resume dict into embeddable chunks.

    Returns a list of {"chunk_index": int, "content": str, "section": str}.
    """
    chunks: list[dict] = []
    idx = 0

    def _add(section: str, content: str) -> None:
        nonlocal idx
        chunks.append({"chunk_index": idx, "section": section, "content": content.strip()})
        idx += 1

    # Summary
    if parsed.get("summary"):
        _add("summary", parsed["summary"])

    # Skills (single chunk)
    skills = parsed.get("skills", [])
    if skills:
        _add("skills", "Skills: " + ", ".join(skills))

    # Experience (one chunk per role)
    for exp in parsed.get("experience", []):
        text = (
            f"{exp.get('title', '')} at {exp.get('company', '')} ({exp.get('duration', '')})\n"
            f"{exp.get('description', '')}"
        )
        _add("experience", text)

    # Education (one chunk per degree)
    for edu in parsed.get("education", []):
        text = (
            f"{edu.get('degree', '')} in {edu.get('field', '')} "
            f"from {edu.get('school', '')} ({edu.get('graduation_year', '')})"
        )
        _add("education", text)

    # Projects (one chunk per project)
    for proj in parsed.get("projects", []):
        techs = ", ".join(proj.get("technologies", []))
        text = f"{proj.get('name', '')}: {proj.get('description', '')}"
        if techs:
            text += f" [{techs}]"
        _add("projects", text)

    # Certifications (single chunk)
    certs = parsed.get("certifications", [])
    if certs:
        _add("certifications", "Certifications: " + ", ".join(certs))

    return chunks


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def process_resume(
    user_id: str,
    pdf_bytes: bytes,
    filename: str,
    label: str,
) -> str:
    """Full resume processing pipeline. Returns the new resume_id.

    Steps:
    1. Upload PDF to Supabase Storage
    2. Parse PDF with Gemini vision
    3. Chunk the parsed resume
    4. Embed each chunk
    5. Store resume row + chunks in DB
    """
    client = database.get_client()

    # 1. Upload to Storage
    storage_path = f"{user_id}/{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{filename}"
    client.storage.from_("resumes").upload(
        path=storage_path,
        file=pdf_bytes,
        file_options={"content-type": "application/pdf"},
    )

    # 2. Parse
    parsed = parse_resume_pdf(pdf_bytes)

    # 3. Chunk
    raw_chunks = chunk_parsed_resume(parsed)

    # 4. Insert resume row (deactivate others first)
    resume_row = database.insert_resume(
        {
            "user_id": user_id,
            "label": label,
            "storage_path": storage_path,
            "parsed_json": parsed,
            "is_active": True,
        }
    )
    resume_id = resume_row["id"]

    # Deactivate all previous resumes for this user
    database.set_active_resume(user_id, resume_id)

    # 5. Embed + store chunks
    chunk_rows = []
    for chunk in raw_chunks:
        embedding = embed_text(chunk["content"])
        chunk_rows.append(
            {
                "resume_id": resume_id,
                "user_id": user_id,
                "chunk_index": chunk["chunk_index"],
                "section": chunk["section"],
                "content": chunk["content"],
                "embedding": embedding,
            }
        )
    database.insert_resume_chunks(chunk_rows)

    return resume_id
