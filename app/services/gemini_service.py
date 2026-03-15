from __future__ import annotations

import itertools

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from pydantic import BaseModel, Field

from app.config import settings


# ---------------------------------------------------------------------------
# Client + key rotation
# ---------------------------------------------------------------------------

def _make_cycle() -> itertools.cycle:
    return itertools.cycle(settings.gemini_keys)


_key_cycle = _make_cycle()
_client = genai.Client(api_key=next(_key_cycle))
_EMBEDDING_MODEL = settings.gemini_embedding_model
_GENERATION_MODEL = settings.gemini_generation_model


def _get_client() -> genai.Client:
    return _client


def _rotate_and_get_client() -> genai.Client:
    global _client
    _client = genai.Client(api_key=next(_key_cycle))
    return _client


def generate_with_rotation(model: str, config: types.GenerateContentConfig, contents) -> str:
    """Call generate_content with automatic key rotation on 429.

    `contents` may be a string or a list of Parts (for multimodal calls).
    """
    client = _get_client()
    keys_tried = 0
    total_keys = len(settings.gemini_keys)
    while keys_tried < total_keys:
        try:
            response = client.models.generate_content(
                model=model, config=config, contents=contents
            )
            return response.text
        except ClientError as e:
            if e.code == 429:
                print("[gemini] quota hit — rotating key")
                client = _rotate_and_get_client()
                keys_tried += 1
            else:
                raise
    raise RuntimeError("All Gemini API keys exhausted their quota")



def _embed_with_rotation(text: str, task_type: str) -> list[float]:
    """Embed text with automatic key rotation on 429."""
    client = _get_client()
    keys_tried = 0
    total_keys = len(settings.gemini_keys)
    while keys_tried < total_keys:
        try:
            response = client.models.embed_content(
                model=_EMBEDDING_MODEL,
                contents=text,
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=768),
            )
            return response.embeddings[0].values
        except ClientError as e:
            if e.code == 429:
                print("[gemini] quota hit — rotating key")
                client = _rotate_and_get_client()
                keys_tried += 1
            else:
                raise
    raise RuntimeError("All Gemini API keys exhausted their quota")


# ---------------------------------------------------------------------------
# Public embedding functions
# ---------------------------------------------------------------------------

def embed_text(text: str) -> list[float]:
    """768-dim embedding for storing documents (retrieval_document)."""
    return _embed_with_rotation(text, task_type="RETRIEVAL_DOCUMENT")


def embed_query(text: str) -> list[float]:
    """768-dim embedding for querying (retrieval_query)."""
    return _embed_with_rotation(text, task_type="RETRIEVAL_QUERY")


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------

class _QualifyResult(BaseModel):
    score: int = Field(ge=0, le=100, description="Fit score 0-100")
    strengths: list[str] = Field(description="Key strengths matching this job")
    gaps: list[str] = Field(description="Notable gaps or missing requirements")


# ---------------------------------------------------------------------------
# Generation functions
# ---------------------------------------------------------------------------

def qualify_job(resume_chunks: list[str], job_description: str) -> dict:
    """Score a candidate against a job description.

    Returns {"score": int, "strengths": [...], "gaps": [...]}.
    """
    resume_text = "\n\n".join(resume_chunks)
    prompt = f"""You are an expert job qualification analyst.

CANDIDATE RESUME (relevant sections):
{resume_text}

JOB DESCRIPTION:
{job_description}

SCORING GUIDELINES:
- 90-100: Excellent match — exceeds most requirements
- 70-89: Good match — meets most requirements with minor gaps
- 55-69: Moderate match — some relevant experience, significant gaps
- 40-54: Poor match — major qualification gaps
- 1-39: Very poor match — fundamental misalignment

Return JSON matching this schema exactly:
{{"score": <int 0-100>, "strengths": [<string>, ...], "gaps": [<string>, ...]}}"""

    raw = generate_with_rotation(
        model=_GENERATION_MODEL,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_QualifyResult,
        ),
        contents=prompt,
    )
    return _QualifyResult.model_validate_json(raw).model_dump()


def generate_summary(
    resume_chunks: list[str],
    job_title: str,
    company: str,
    job_description: str,
) -> str:
    """Generate a 3-4 sentence tailored professional summary."""
    resume_text = "\n\n".join(resume_chunks)
    prompt = f"""You are an expert resume writer.

Write a tailored 3-4 sentence professional summary for a candidate applying to {job_title} at {company}.

CANDIDATE RESUME (relevant sections):
{resume_text}

JOB DESCRIPTION:
{job_description}

Requirements:
- First person, present tense
- Highlight skills/experience that directly match the job
- Professional and concise
- Return ONLY the summary text, no labels or headers"""

    return generate_with_rotation(
        model=_GENERATION_MODEL,
        config=types.GenerateContentConfig(),
        contents=prompt,
    ).strip()


def generate_cover_letter(
    resume_chunks: list[str],
    job_title: str,
    company: str,
    job_description: str,
    hook_project: str | None = None,
) -> str:
    """Generate a tailored cover letter, optionally anchored by a hook project."""
    resume_text = "\n\n".join(resume_chunks)
    hook_section = (
        f"\nFeatured project hook to weave into the letter:\n{hook_project}\n"
        if hook_project
        else ""
    )
    prompt = f"""You are an expert cover letter writer.

Write a tailored cover letter for a candidate applying to {job_title} at {company}.

CANDIDATE RESUME (relevant sections):
{resume_text}

JOB DESCRIPTION:
{job_description}
{hook_section}
Requirements:
- 3-4 short paragraphs
- Specific, not generic — reference the company and role directly
- Highlight the strongest alignment between the candidate and the role
- Professional but personable tone
- Return ONLY the cover letter text, no subject lines or metadata"""

    return generate_with_rotation(
        model=_GENERATION_MODEL,
        config=types.GenerateContentConfig(),
        contents=prompt,
    ).strip()
