# Standard library
import itertools

# Third-party
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel, Field

# Local
from config import Config as config
from job_model import Job
from resume_processor import ResumeData

_key_cycle = itertools.cycle(config.GEMINI_API_KEYS)
_current_key = next(_key_cycle)
client = genai.Client(api_key=_current_key)

THRESHOLD = 80


class GeminiOverloadError(Exception):
    """Raised when Gemini returns 503 (high demand). Carries the prompt so the user can run it manually."""
    def __init__(self, prompt: str):
        self.prompt = prompt
        super().__init__("Gemini 503: model overloaded — use fallback prompt")


class QualifierData(BaseModel):
    qualification_score: int = Field(description="Overall qualification score (0-100)")
    ai_reasoning: str = Field(description="Detailed explanation of the score")
    matching_strengths: list[str] = Field(description="Key strengths that match the job")
    job_link: str = Field(description="Copy the job URL exactly as provided in the job details")


def _create_analysis_prompt(jobs: list[Job], resume: ResumeData) -> str:
    experience_lines = "\n".join(
        f"  - {e.title} at {e.company} ({e.duration}): {e.description}"
        for e in resume.experience
    )
    project_lines = "\n".join(
        f"  - {p.name}: {p.description} [{', '.join(p.technologies)}]"
        for p in resume.projects
    )
    education_lines = "\n".join(
        f"  - {e.degree} in {e.field} from {e.school} ({e.graduation_year})"
        for e in resume.education
    )

    job_sections = "\n\n".join(
        f"JOB {i + 1}:\n"
        f"- Title: {job.role}\n"
        f"- Company: {job.company}\n"
        f"- Link: {job.link}\n"
        + (f"- Job Level: {job.job_level}\n" if job.job_level else "")
        + (f"- Salary: {job.salary}\n" if job.salary else "")
        + f"- Description: {job.description}"
        for i, job in enumerate(jobs)
    )

    return f"""
You are an expert job qualification analyst. Evaluate how well the candidate's resume matches each job listed below.
Return one result per job, in the same order as the jobs are listed.

{job_sections}

CANDIDATE RESUME:
- Summary: {resume.summary}
- Education:
{education_lines or "  None listed"}
- Experience:
{experience_lines or "  None listed"}
- Technical Skills: {', '.join(resume.skills.technical) or 'None'}
- Programming Languages: {', '.join(resume.skills.programming_languages) or 'None'}
- Frameworks: {', '.join(resume.skills.frameworks) or 'None'}
- Tools: {', '.join(resume.skills.tools) or 'None'}
- Certifications: {', '.join(resume.certifications) or 'None'}
- Projects:
{project_lines or "  None listed"}

SCORING GUIDELINES:
- 90-100: Excellent match — exceeds most requirements
- 70-89: Good match — meets most requirements with minor gaps
- 55-69: Moderate match — some relevant experience, significant gaps
- 40-54: Poor match — major qualification gaps
- 1-39: Very poor match — fundamental misalignment

For each job, provide a qualification score, reasoning, and matching strengths.
""".strip()


def _create_fallback_prompt(jobs: list[Job], resume: ResumeData) -> str:
    """Prompt variant with explicit JSON instructions for pasting directly into Gemini."""
    base = _create_analysis_prompt(jobs, resume)
    return base + """

RESPONSE FORMAT:
Reply with a valid JSON array only — no markdown fences, no extra text. Each element must have exactly these fields:
- "qualification_score": integer 0-100
- "ai_reasoning": string explaining the score
- "matching_strengths": array of strings (key strengths that match the job)
- "job_link": the exact URL from the job details above (copy it character-for-character)

Jobs with qualification_score >= 80 are considered a good match."""


def call_gemini(jobs: list[Job], resume: ResumeData) -> list[QualifierData]:
    global client, _current_key
    prompt = _create_analysis_prompt(jobs, resume)

    keys_tried = 0
    while keys_tried < len(config.GEMINI_API_KEYS):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    system_instruction=prompt,
                    response_mime_type="application/json",
                    response_schema=list[QualifierData],
                ),
                contents="Analyze the jobs.",
            )
            return response.parsed
        except ClientError as e:
            if e.code == 429:
                _current_key = next(_key_cycle)
                client = genai.Client(api_key=_current_key)
                print(f"[gemini] quota hit — rotating to next key")
                keys_tried += 1
            else:
                raise
        except ServerError as e:
            if e.code == 503:
                raise GeminiOverloadError(_create_fallback_prompt(jobs, resume))
            raise
    raise RuntimeError("All Gemini API keys exhausted their quota")


def filtered_jobs(jobs: list[Job], resume: ResumeData) -> list[Job]:
    analyzed_jobs = call_gemini(jobs, resume)

    link_to_job = {job.link: job for job in jobs}
    qualified: list[Job] = []
    for result in analyzed_jobs:
        if result.qualification_score < THRESHOLD:
            continue
        job = link_to_job.get(result.job_link)
        if job is None:
            continue
        job.score = result.qualification_score
        notes = result.ai_reasoning
        if result.matching_strengths:
            notes += "\n\nStrengths: " + "; ".join(result.matching_strengths)
        job.notes = notes
        qualified.append(job)
    return qualified