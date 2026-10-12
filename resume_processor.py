# Standard library
import json
import os
import sys

# Third-party
from pydantic import BaseModel
import PyPDF2

# Local
import gemini_client


# --- Structured output schema ---

class PersonalInfo(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""


class Education(BaseModel):
    degree: str = ""
    field: str = ""
    school: str = ""
    graduation_year: str = ""
    gpa: str = ""


class Experience(BaseModel):
    title: str = ""
    company: str = ""
    duration: str = ""
    description: str = ""
    key_achievements: list[str] = []


class Skills(BaseModel):
    technical: list[str] = []
    programming_languages: list[str] = []
    frameworks: list[str] = []
    tools: list[str] = []
    soft_skills: list[str] = []


class Project(BaseModel):
    name: str = ""
    description: str = ""
    technologies: list[str] = []
    url: str = ""


class ResumeData(BaseModel):
    personal_info: PersonalInfo = PersonalInfo()
    education: list[Education] = []
    experience: list[Experience] = []
    skills: Skills = Skills()
    certifications: list[str] = []
    projects: list[Project] = []
    total_years_experience: int = 0
    summary: str = ""


# --- Core functions ---

def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text.strip()


def analyze_resume(resume_text: str) -> ResumeData:
    data = gemini_client.generate_json(
        system_instruction="Extract structured information from the resume.",
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

