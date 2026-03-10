# Third-party
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Local
from config import Config as config
from job_model import Job
from resume_processor import ResumeData

client = genai.Client(api_key=config.GEMINI_API_KEY)

THRESHOLD = 80

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


def call_gemini(jobs: list[Job], resume: ResumeData) -> list[QualifierData]:
    prompt = _create_analysis_prompt(jobs, resume)

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


def filtered_jobs(jobs: list[Job], resume: ResumeData) -> list[QualifierData]:
    analyzed_jobs = call_gemini(jobs, resume)

    link_to_job = {job.link: job for job in jobs}
    return [link_to_job[result.job_link] for result in analyzed_jobs if result.qualification_score >= THRESHOLD and result.job_link in link_to_job]