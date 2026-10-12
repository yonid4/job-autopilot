# Standard library
import json
from datetime import date
import os
import sys

# Third-party
from pydantic import BaseModel, Field, computed_field
import PyPDF2

# Local
import gemini_client


def months_to_years(months: int) -> int:
    # 3-12 months counts as one year; past that, round up only after 7+ months into the next year
    if months < 3:
        return 0
    if months <= 12:
        return 1
    years, remainder = divmod(months, 12)
    return years + 1 if remainder >= 7 else years


# --- Structured output schema ---

class PersonalInfo(BaseModel):
    name: str = Field(default="", description="Full name of the candidate.")
    email: str = Field(default="", description="Email address.")
    phone: str = Field(default="", description="Phone number, formatted as written on the resume.")
    location: str = Field(default="", description="City and state/country, e.g. 'San Francisco, CA'.")
    linkedin: str = Field(default="", description="Full LinkedIn profile URL. Use the hyperlink target if one exists.")
    github: str = Field(default="", description="Full GitHub profile URL (the person's profile, not a project repo).")
    portfolio: str = Field(default="", description="Full URL of a personal website or portfolio. Use the hyperlink target if one exists.")
    other_links: list[str] = Field(default=[], description="Any other personal profile URLs in the header (e.g. Kaggle, Medium). Exclude LinkedIn, GitHub, portfolio, and project links.")


class Education(BaseModel):
    degree: str = Field(default="", description="Degree abbreviation as written, e.g. 'B.S.', 'M.S.', 'Ph.D.'.")
    field: str = Field(default="", description="Field of study / major, e.g. 'Computer Science'.")
    school: str = Field(default="", description="Full name of the institution.")
    graduation_year: str = Field(default="", description="Four-digit graduation year (expected year if not yet graduated).")
    gpa: str = Field(default="", description="GPA exactly as written, e.g. '3.8/4.0'. Empty if not listed.")
    relevant_courses: list[str] = Field(default=[], description="Each course listed under relevant coursework, one per item.")


class Experience(BaseModel):
    title: str = Field(default="", description="Job title, including qualifiers like '(Contract)' or 'Intern'.")
    company: str = Field(default="", description="Company name, including any descriptor in parentheses.")
    duration: str = Field(default="", description="Date range as written, e.g. 'Jan. 2025 - May 2025'.")
    description: str = Field(default="", description="A one-to-two sentence overview of the role: what the candidate built or owned, for whom, and with which core technologies. Write it from the bullet points if the resume has no role summary. Use only facts stated in the resume.")
    key_achievements: list[str] = Field(default=[], description="Each bullet point for this role, copied verbatim, one per item.")


class Skills(BaseModel):
    technical: list[str] = Field(default=[], description="Technical concepts and methods, e.g. 'RAG', 'REST APIs', 'OAuth 2.0'.")
    programming_languages: list[str] = Field(default=[], description="Programming and query languages, e.g. 'Python', 'SQL'.")
    frameworks: list[str] = Field(default=[], description="Libraries and frameworks, e.g. 'FastAPI', 'React', 'LangGraph'.")
    tools: list[str] = Field(default=[], description="Tools, platforms, databases, and third-party APIs, e.g. 'Docker', 'PostgreSQL', 'Gemini API'.")
    soft_skills: list[str] = Field(default=[], description="Soft skills explicitly listed on the resume. Do not infer them.")


class Project(BaseModel):
    name: str = Field(default="", description="Project name as written.")
    description: str = Field(default="", description="All bullet points for the project, copied verbatim and joined into one paragraph.")
    technologies: list[str] = Field(default=[], description="Technologies listed for the project.")
    url: str = Field(default="", description="Full URL of the project link (GitHub repo or live site). Use the hyperlink target, not the link text.")


class ResumeData(BaseModel):
    personal_info: PersonalInfo = PersonalInfo()
    education: list[Education] = []
    experience: list[Experience] = Field(default=[], description="Professional work experience only (jobs, internships, contracts). Personal projects go in projects.")
    skills: Skills = Skills()
    certifications: list[str] = Field(default=[], description="Certifications, one per item.")
    projects: list[Project] = []
    total_months_experience: int = Field(default=0, description="Total months of professional work experience across all experience entries, counting both start and end months. Treat 'Present' as the current date. Do not double-count overlapping roles.")
    summary: str = Field(default="", description="A 2-3 sentence professional summary of the candidate: career level, main focus areas, strongest technologies, and standout results. Use the resume's own summary section if it has one; otherwise write one from the experience, projects, and skills. Use only facts stated in the resume.")

    @computed_field
    @property
    def total_years_experience(self) -> int:
        return months_to_years(self.total_months_experience)


# --- Core functions ---

def extract_links_from_page(page) -> list[str]:
    # Hyperlink targets live in /Link annotations, not in the page text
    links = []
    for annot in page.get("/Annots") or []:
        annot = annot.get_object()
        uri = annot.get("/A", {}).get("/URI")
        if annot.get("/Subtype") != "/Link" or not uri:
            continue
        x1, y1, x2, y2 = (float(v) for v in annot["/Rect"])
        anchor = []

        def visitor(text, cm, tm, _font_dict, _font_size):
            # Text position in page space = text matrix translated by the CTM
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            if x1 - 1 <= x <= x2 + 1 and y1 - 2 <= y <= y2 + 2:
                anchor.append(text)

        page.extract_text(visitor_text=visitor)
        anchor_text = " ".join("".join(anchor).split()).strip(" |")
        links.append(f"{anchor_text or '(no text)'} -> {uri}")
    return links


def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    links = []
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() + "\n"
            links += extract_links_from_page(page)
    if links:
        text += "\nHyperlinks (link text -> URL, in document order):\n" + "\n".join(links)
    return text.strip()


def analyze_resume(resume_text: str) -> ResumeData:
    data = gemini_client.generate_json(
        system_instruction=(
            "Extract structured information from the resume. "
            "If there is a hyperlink, set the URL to the hyperlink instead of the text. "
            "Always fill the summary and each experience description, writing them from the resume content if needed. "
            "For any other field not present in the resume, leave it as an empty string or empty list. "
            "Never write placeholder values like 'null', 'N/A', or 'None'. "
            f"Today's date is {date.today():%B %Y}."
        ),
        contents=resume_text,
        response_schema=ResumeData,
    )
    if data is None:
        raise RuntimeError("Gemini returned no resume data")
    return data


RESUME_JSON_PATH = os.path.join(os.path.dirname(__file__), "resume.json")


def load_resume() -> ResumeData:
    with open(RESUME_JSON_PATH) as f:
        return ResumeData.model_validate(json.load(f))


def process_resume(file_path: str) -> ResumeData:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    resume_text = extract_text_from_pdf(file_path)
    data = analyze_resume(resume_text)
    with open(RESUME_JSON_PATH, "w") as f:
        json.dump(data.model_dump(), f, indent=2)
    print(f"Resume saved to {RESUME_JSON_PATH}")
    return load_resume()


def main() -> None:
    file_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "resume.pdf"
    )
    process_resume(file_path)


if __name__ == "__main__":
    main()

