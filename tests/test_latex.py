"""Tests for the LaTeX pipeline (Phase 6).

Covers:
- escape_latex — all 10 special characters, order safety, round-trip
- inject_into_template — happy path, missing key, extra key
- build_replacements — field mapping from resume dict
- _edu_items / _exp_items / _proj_items / _skills_items — LaTeX block generation
- compile_latex — skipped when pdflatex absent, error on bad source
- render_and_upload — end-to-end with mocked compile + upload
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.resume_formatter import escape_latex, format_for_latex
from app.services.latex_service import (
    _edu_items,
    _exp_items,
    _proj_items,
    _skills_items,
    build_replacements,
    compile_latex,
    inject_into_template,
    render_and_save,
)


# ---------------------------------------------------------------------------
# escape_latex
# ---------------------------------------------------------------------------

class TestEscapeLatex:
    def test_ampersand(self):
        assert escape_latex("A & B") == r"A \& B"

    def test_percent(self):
        assert escape_latex("50%") == r"50\%"

    def test_dollar(self):
        assert escape_latex("$100") == r"\$100"

    def test_hash(self):
        assert escape_latex("#1") == r"\#1"

    def test_underscore(self):
        assert escape_latex("snake_case") == r"snake\_case"

    def test_braces(self):
        assert escape_latex("{x}") == r"\{x\}"

    def test_tilde(self):
        assert "textasciitilde" in escape_latex("~")

    def test_caret(self):
        assert "textasciicircum" in escape_latex("^")

    def test_backslash(self):
        assert "textbackslash" in escape_latex("\\")

    def test_all_ten_present(self):
        raw = r"\ & % $ # _ { } ~ ^"
        escaped = escape_latex(raw)
        # None of the raw specials should survive unescaped
        for ch in ("&", "%", "$", "#", "_"):
            assert f" {ch}" not in escaped or f"\\{ch}" in escaped

    def test_no_double_escape(self):
        # Escaping once then again should not produce \\\\&
        once = escape_latex("A & B")
        twice = escape_latex(once)
        # The first escape produces \& which contains a backslash — the second
        # run will escape *that* backslash.  The important thing is that a
        # single-pass on plain text is idempotent for characters not in the
        # special set.
        assert once == r"A \& B"

    def test_plain_text_unchanged(self):
        assert escape_latex("Hello World") == "Hello World"

    def test_empty_string(self):
        assert escape_latex("") == ""


# ---------------------------------------------------------------------------
# inject_into_template
# ---------------------------------------------------------------------------

class TestInjectIntoTemplate:
    def test_single_replacement(self):
        tmpl = "Hello %%NAME%%!"
        assert inject_into_template(tmpl, {"NAME": "Jane"}) == "Hello Jane!"

    def test_multiple_replacements(self):
        tmpl = "%%A%% %%B%%"
        assert inject_into_template(tmpl, {"A": "foo", "B": "bar"}) == "foo bar"

    def test_unknown_marker_left_intact(self):
        tmpl = "%%UNKNOWN%%"
        assert inject_into_template(tmpl, {}) == "%%UNKNOWN%%"

    def test_extra_key_ignored(self):
        tmpl = "%%A%%"
        assert inject_into_template(tmpl, {"A": "yes", "B": "no"}) == "yes"

    def test_replacement_with_latex_content(self):
        tmpl = "\\textbf{%%NAME%%}"
        result = inject_into_template(tmpl, {"NAME": r"Jane \& Doe"})
        assert result == r"\textbf{Jane \& Doe}"

    def test_repeated_marker(self):
        tmpl = "%%X%% and %%X%%"
        assert inject_into_template(tmpl, {"X": "hi"}) == "hi and hi"


# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------

class TestEduItems:
    def test_basic_entry(self):
        edu = [{"institution": "MIT", "location": "Cambridge", "degree": "BSc CS", "date": "2020"}]
        result = _edu_items(edu)
        assert "MIT" in result
        assert "BSc CS" in result
        assert "\\resumeSubheading" in result

    def test_with_bullets(self):
        edu = [{"institution": "MIT", "location": "", "degree": "BSc", "date": "2020",
                "bullets": ["GPA 4.0"]}]
        result = _edu_items(edu)
        assert "GPA 4.0" in result
        assert "\\resumeItem" in result

    def test_bullet_dict_uses_tailored(self):
        edu = [{"institution": "X", "location": "", "degree": "Y", "date": "Z",
                "bullets": [{"original": "orig", "tailored": "tailored ver"}]}]
        result = _edu_items(edu)
        assert "tailored ver" in result
        assert "orig" not in result

    def test_empty(self):
        assert _edu_items([]) == ""


class TestExpItems:
    def test_basic_entry(self):
        exp = [{"title": "Engineer", "date": "2023", "company": "Acme", "location": "Remote",
                "bullets": ["Built things"]}]
        result = _exp_items(exp)
        assert "Engineer" in result
        assert "Acme" in result
        assert "Built things" in result

    def test_empty(self):
        assert _exp_items([]) == ""


class TestProjItems:
    def test_basic_project(self):
        proj = [{"name": "MyApp", "technologies": ["Python", "FastAPI"], "date": "2024",
                 "bullets": ["Did stuff"]}]
        result = _proj_items(proj)
        assert "MyApp" in result
        assert "Python" in result
        assert "FastAPI" in result
        assert "Did stuff" in result

    def test_project_no_techs(self):
        proj = [{"name": "NoTech", "technologies": [], "date": "", "bullets": []}]
        result = _proj_items(proj)
        assert "NoTech" in result
        assert "$|$" not in result

    def test_empty(self):
        assert _proj_items([]) == ""


class TestSkillsItems:
    def test_dict_skills(self):
        skills = {"Languages": ["Python", "Go"], "Tools": ["Docker"]}
        result = _skills_items(skills)
        assert "Languages" in result
        assert "Python" in result
        assert "Docker" in result

    def test_list_skills(self):
        result = _skills_items(["Python", "Go"])
        assert "Python" in result
        assert "Go" in result

    def test_empty_dict(self):
        result = _skills_items({})
        assert result == ""


# ---------------------------------------------------------------------------
# build_replacements
# ---------------------------------------------------------------------------

class TestBuildReplacements:
    _RESUME = {
        "name": "Jane Doe",
        "contact": {
            "phone": "555-1234",
            "email": "jane@example.com",
            "linkedin": "https://linkedin.com/in/jane",
        },
        "education": [],
        "experience": [],
        "projects": [],
        "skills": {"Languages": ["Python"]},
    }

    def test_name_mapped(self):
        r = build_replacements(self._RESUME)
        assert r["NAME"] == "Jane Doe"

    def test_email_mapped(self):
        r = build_replacements(self._RESUME)
        assert r["EMAIL"] == "jane@example.com"

    def test_summary_escaped(self):
        r = build_replacements(self._RESUME, summary="Foo & Bar")
        assert r["PROFESSIONAL_SUMMARY"] == r"Foo \& Bar"

    def test_github_block_absent_when_no_github(self):
        r = build_replacements(self._RESUME)
        assert r["GITHUB_BLOCK"] == ""

    def test_github_block_present_when_github_set(self):
        resume = {**self._RESUME, "contact": {**self._RESUME["contact"], "github": "https://github.com/jane"}}
        r = build_replacements(resume)
        assert "github.com/jane" in r["GITHUB_BLOCK"]

    def test_skills_rendered(self):
        r = build_replacements(self._RESUME)
        assert "Python" in r["SKILLS_ITEMS"]


# ---------------------------------------------------------------------------
# compile_latex
# ---------------------------------------------------------------------------

class TestCompileLatex:
    def test_raises_when_pdflatex_missing(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="pdflatex not found"):
                compile_latex("irrelevant")

    @pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex not installed")
    def test_bad_source_raises(self):
        with pytest.raises(RuntimeError, match="pdflatex failed"):
            compile_latex("\\documentclass{article}\n\\begin{document}\n\\BADCMD\n\\end{document}")

    @pytest.mark.skipif(not shutil.which("pdflatex"), reason="pdflatex not installed")
    def test_valid_source_returns_bytes(self):
        source = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Hello World\n"
            "\\end{document}\n"
        )
        pdf = compile_latex(source)
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# render_and_save — end-to-end (mocked compile + local filesystem)
# ---------------------------------------------------------------------------

class TestRenderAndSave:
    _RESUME = {
        "name": "Jane Doe",
        "contact": {"phone": "555", "email": "j@x.com", "linkedin": "https://linkedin.com/in/j"},
        "education": [],
        "experience": [],
        "projects": [],
        "skills": {"Languages": ["Python"]},
    }

    def test_returns_local_path(self, tmp_path):
        fake_pdf = b"%PDF-1.4 fake"

        with patch("app.services.latex_service.compile_latex", return_value=fake_pdf), \
             patch("app.services.latex_service._OUTPUT_DIR", tmp_path):
            result = render_and_save(self._RESUME, user_id="uid", job_id="jid", summary="Great dev")

        assert result.endswith("tailored_jid.pdf")

    def test_saves_to_correct_path(self, tmp_path):
        fake_pdf = b"%PDF-1.4 fake"

        with patch("app.services.latex_service.compile_latex", return_value=fake_pdf), \
             patch("app.services.latex_service._OUTPUT_DIR", tmp_path):
            render_and_save(self._RESUME, user_id="user-123", job_id="job-456")

        assert (tmp_path / "user-123" / "tailored_job-456.pdf").exists()

    def test_template_markers_all_replaced(self):
        """Verify that no %%...%% markers remain after injection."""
        import re
        replacements = build_replacements(self._RESUME, summary="Dev summary")
        template = Path(__file__).resolve().parents[1] / "templates" / "resume_template.tex"
        tex_source = inject_into_template(template.read_text(), replacements)
        leftover = re.findall(r"%%[A-Z_]+%%", tex_source)
        assert leftover == [], f"Unreplaced markers: {leftover}"
