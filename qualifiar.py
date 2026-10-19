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
    main_gap: str = Field(description="One sentence: the biggest reason the score is not higher")
    job_number: int = Field(description="The number N from the job's 'JOB N' label")


def _create_analysis_prompt(jobs: list[Job], resume: ResumeData) -> str:
    experience_lines = "\n".join(
        f"  - {e.title} at {e.company} ({e.duration}): {e.description}"
        + "".join(f"\n      * {a}" for a in e.key_achievements)
        for e in resume.experience
    )
    project_lines = "\n".join(
        f"  - {p.name}: {p.description} [{', '.join(p.technologies)}]"
        for p in resume.projects
    )
    education_lines = "\n".join(
        f"  - {e.degree} in {e.field} from {e.school} ({e.graduation_year})"
        + (f", GPA {e.gpa}" if e.gpa else "")
        + (f"\n    Relevant courses: {', '.join(e.relevant_courses)}" if e.relevant_courses else "")
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
Return one result per job, in the same order as the jobs are listed, each with the job's number from its "JOB N" label.

{job_sections}

CANDIDATE RESUME:
- Summary: {resume.summary or 'None'}
- Location: {resume.personal_info.location or 'Not listed'}
- Total Professional Experience: {resume.total_years_experience} year(s) ({resume.total_months_experience} months)
- Education:
{education_lines or "  None listed"}
- Experience:
{experience_lines or "  None listed"}
- Technical Skills: {', '.join(resume.skills.technical) or 'None'}
- Programming Languages: {', '.join(resume.skills.programming_languages) or 'None'}
- Frameworks: {', '.join(resume.skills.frameworks) or 'None'}
- Tools: {', '.join(resume.skills.tools) or 'None'}
- Soft Skills: {', '.join(resume.skills.soft_skills) or 'None'}
- Certifications: {', '.join(resume.certifications) or 'None'}
- Projects:
{project_lines or "  None listed"}

SCORING GUIDELINES:
- 90-100: Excellent match — exceeds most requirements
- 70-89: Good match — meets most requirements with minor gaps
- 55-69: Moderate match — some relevant experience, significant gaps
- 40-54: Poor match — major qualification gaps
- 1-39: Very poor match — fundamental misalignment

For each job, provide a qualification score, reasoning, matching strengths, and the main gap.
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
- "main_gap": one sentence, the biggest reason the score is not higher
- "job_number": integer N from the job's "JOB N" label above

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


def _one_line(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _match_results(jobs: list[Job], results: list[QualifierData]) -> list[tuple[Job, QualifierData]]:
    """Pair each result with its job by the "JOB N" number. Numbers out of
    range or already used are logged and ignored rather than guessed at."""
    matched: dict[int, QualifierData] = {}
    for result in results:
        n = result.job_number
        if not 1 <= n <= len(jobs):
            print(f"[gemini] score {result.qualification_score} for job number {n} "
                  f"(sent {len(jobs)}), ignored")
        elif n in matched:
            print(f"[gemini] second score {result.qualification_score} for JOB {n} "
                  f"({jobs[n - 1].company} — {jobs[n - 1].role}), ignored")
        else:
            matched[n] = result
    return [(jobs[n - 1], result) for n, result in sorted(matched.items())]


def _score_jobs(jobs: list[Job], resume: ResumeData) -> list[tuple[Job, QualifierData]]:
    """Score every job, re-sending once any job that got no usable result.

    The re-send is best effort: if it fails (a 503, or every key out of
    quota), the first pass's scores are kept and the jobs it was for are
    logged as unscored instead of failing the whole batch."""
    scored = _match_results(jobs, call_gemini(jobs, resume) or [])
    answered = {id(job) for job, _ in scored}
    missing = [job for job in jobs if id(job) not in answered]
    if missing:
        print(f"[gemini] no usable score for {len(missing)} job(s), re-sending them once...")
        try:
            scored += _match_results(missing, call_gemini(missing, resume) or [])
        except GeminiOverloadError:
            print("[gemini] 503 overload on the re-send")
        except Exception as e:
            print(f"[gemini] re-send failed: {e}")
        answered = {id(job) for job, _ in scored}
        for job in missing:
            if id(job) not in answered:
                print(f"[gemini] no score returned for {job.company} — {job.role} ({job.link})")
    return scored


def filtered_jobs(jobs: list[Job], resume: ResumeData) -> list[Job]:
    qualified: list[Job] = []
    for job, result in _score_jobs(jobs, resume):
        score = result.qualification_score
        if score < THRESHOLD:
            # The reasoning leads with strengths, so a cut-down copy hid the
            # gap; the dedicated field says why in one line.
            print(f"[gemini] rejected (score {score}): {job.company} — {job.role} — "
                  f"gap: {_one_line(result.main_gap or result.ai_reasoning)}")
            continue
        job.score = result.qualification_score
        notes = result.ai_reasoning
        if result.matching_strengths:
            notes += "\n\nStrengths: " + "; ".join(result.matching_strengths)
        job.notes = notes
        qualified.append(job)
    return qualified