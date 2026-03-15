from __future__ import annotations

import pytest

from app.services.resume_service import chunk_parsed_resume


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def full_resume() -> dict:
    return {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-1234",
        "summary": "Experienced software engineer with a focus on backend systems.",
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "experience": [
            {
                "title": "Senior Engineer",
                "company": "Acme Corp",
                "duration": "2021-present",
                "description": "Led backend infrastructure work.",
            },
            {
                "title": "Engineer",
                "company": "Startup Inc",
                "duration": "2018-2021",
                "description": "Built REST APIs and data pipelines.",
            },
        ],
        "education": [
            {
                "degree": "B.Sc.",
                "field": "Computer Science",
                "school": "State University",
                "graduation_year": "2018",
            }
        ],
        "projects": [
            {
                "name": "AutoDeploy",
                "description": "CI/CD automation tool",
                "technologies": ["Python", "Docker"],
            }
        ],
        "certifications": ["AWS Solutions Architect"],
    }


@pytest.fixture
def minimal_resume() -> dict:
    return {
        "name": "John Smith",
        "summary": None,
        "skills": [],
        "experience": [],
        "education": [],
        "projects": [],
        "certifications": [],
    }


# ---------------------------------------------------------------------------
# chunk_parsed_resume
# ---------------------------------------------------------------------------

class TestChunkParsedResume:
    def test_returns_list_of_dicts(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        assert isinstance(chunks, list)
        assert all(isinstance(c, dict) for c in chunks)

    def test_chunk_has_required_keys(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        for chunk in chunks:
            assert "chunk_index" in chunk
            assert "section" in chunk
            assert "content" in chunk

    def test_chunk_indices_are_sequential(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_section_values_are_valid(self, full_resume):
        valid_sections = {"summary", "skills", "experience", "education", "projects", "certifications"}
        chunks = chunk_parsed_resume(full_resume)
        for chunk in chunks:
            assert chunk["section"] in valid_sections

    def test_full_resume_chunk_count(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        # 1 summary + 1 skills + 2 experience + 1 education + 1 project + 1 certification = 7
        assert len(chunks) == 7

    def test_minimal_resume_produces_no_chunks(self, minimal_resume):
        chunks = chunk_parsed_resume(minimal_resume)
        assert len(chunks) == 0

    def test_summary_chunk_content(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        summary_chunks = [c for c in chunks if c["section"] == "summary"]
        assert len(summary_chunks) == 1
        assert "backend systems" in summary_chunks[0]["content"]

    def test_skills_chunk_content(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        skill_chunks = [c for c in chunks if c["section"] == "skills"]
        assert len(skill_chunks) == 1
        content = skill_chunks[0]["content"]
        assert "Python" in content
        assert "FastAPI" in content

    def test_experience_chunks_one_per_role(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        exp_chunks = [c for c in chunks if c["section"] == "experience"]
        assert len(exp_chunks) == 2

    def test_experience_chunk_includes_company(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        exp_chunks = [c for c in chunks if c["section"] == "experience"]
        companies = {c["content"] for c in exp_chunks}
        assert any("Acme Corp" in c for c in companies)
        assert any("Startup Inc" in c for c in companies)

    def test_project_chunk_includes_technologies(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        proj_chunks = [c for c in chunks if c["section"] == "projects"]
        assert len(proj_chunks) == 1
        assert "Docker" in proj_chunks[0]["content"]

    def test_certification_chunk(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        cert_chunks = [c for c in chunks if c["section"] == "certifications"]
        assert len(cert_chunks) == 1
        assert "AWS Solutions Architect" in cert_chunks[0]["content"]

    def test_resume_without_optional_fields(self):
        resume = {
            "name": "Test User",
            "summary": "A summary.",
            "skills": ["Go"],
            "experience": [],
            "education": [],
            "projects": [],
            "certifications": [],
        }
        chunks = chunk_parsed_resume(resume)
        sections = {c["section"] for c in chunks}
        assert "summary" in sections
        assert "skills" in sections
        assert "experience" not in sections

    def test_content_is_stripped(self, full_resume):
        chunks = chunk_parsed_resume(full_resume)
        for chunk in chunks:
            assert chunk["content"] == chunk["content"].strip()
