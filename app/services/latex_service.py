"""LaTeX resume rendering service.

Converts a formatted (escaped) resume dict into a PDF via pdflatex,
then saves the PDF to the local filesystem.

Public API
----------
render_and_save(latex_resume, *, user_id, job_id) -> str
    Returns the absolute path of the saved PDF.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.utils.resume_formatter import escape_latex

# ---------------------------------------------------------------------------
# Template location
# ---------------------------------------------------------------------------

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "resume_template.tex"
_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "uploads" / "tailored"


# ---------------------------------------------------------------------------
# Placeholder injection
# ---------------------------------------------------------------------------

def inject_into_template(template_text: str, replacements: dict[str, str]) -> str:
    """Replace every %%KEY%% marker in *template_text* with the matching value.

    Keys in *replacements* should be given **without** the ``%%`` delimiters,
    e.g. ``{"NAME": "Jane Doe"}``.  Unknown markers are left as-is.
    """
    result = template_text
    for key, value in replacements.items():
        result = result.replace(f"%%{key}%%", value)
    return result


# ---------------------------------------------------------------------------
# Resume-dict → LaTeX block builders
# ---------------------------------------------------------------------------

def _edu_items(education: list[dict]) -> str:
    """Render education entries as LaTeX."""
    lines: list[str] = []
    for edu in education:
        institution = edu.get("institution", "")
        location = edu.get("location", "")
        degree = edu.get("degree", "")
        date = edu.get("date", "")
        lines.append(
            f"    \\resumeSubheading\n"
            f"      {{{institution}}}{{{location}}}\n"
            f"      {{{degree}}}{{{date}}}"
        )
        bullets = edu.get("bullets", [])
        if bullets:
            lines.append("      \\resumeItemListStart")
            for b in bullets:
                text = b if isinstance(b, str) else b.get("tailored", b.get("original", ""))
                lines.append(f"        \\resumeItem{{{text}}}")
            lines.append("      \\resumeItemListEnd")
    return "\n".join(lines)


def _exp_items(experience: list[dict]) -> str:
    """Render experience entries as LaTeX."""
    lines: list[str] = []
    for exp in experience:
        title = exp.get("title", "")
        date = exp.get("date", "")
        company = exp.get("company", "")
        location = exp.get("location", "")
        lines.append(
            f"    \\resumeSubheading\n"
            f"      {{{title}}}{{{date}}}\n"
            f"      {{{company}}}{{{location}}}"
        )
        bullets = exp.get("bullets", [])
        if bullets:
            lines.append("      \\resumeItemListStart")
            for b in bullets:
                text = b if isinstance(b, str) else b.get("tailored", b.get("original", ""))
                lines.append(f"        \\resumeItem{{{text}}}")
            lines.append("      \\resumeItemListEnd")
    return "\n".join(lines)


def _proj_items(projects: list[dict]) -> str:
    """Render project entries as LaTeX."""
    lines: list[str] = []
    for proj in projects:
        name = proj.get("name", "")
        techs = proj.get("technologies", [])
        if isinstance(techs, list):
            tech_str = ", ".join(techs)
        else:
            tech_str = str(techs)
        date = proj.get("date", "")
        heading = f"\\textbf{{{name}}}"
        if tech_str:
            heading += f" $|$ \\emph{{{tech_str}}}"
        lines.append(f"      \\resumeProjectHeading\n          {{{heading}}}{{{date}}}")
        bullets = proj.get("bullets", [])
        if bullets:
            lines.append("          \\resumeItemListStart")
            for b in bullets:
                text = b if isinstance(b, str) else b.get("tailored", b.get("original", ""))
                lines.append(f"            \\resumeItem{{{text}}}")
            lines.append("          \\resumeItemListEnd")
    return "\n".join(lines)


def _skills_items(skills: dict | list) -> str:
    """Render the skills section as LaTeX key: value lines."""
    lines: list[str] = []
    if isinstance(skills, dict):
        for category, items in skills.items():
            if isinstance(items, list):
                value = ", ".join(str(i) for i in items)
            else:
                value = str(items)
            lines.append(f"\\textbf{{{escape_latex(str(category))}}}" + "{: " + value + "} \\\\")
    elif isinstance(skills, list):
        lines.append(", ".join(str(s) for s in skills))
    return "\n     ".join(lines)


def _github_block(github_url: str | None, github_display: str | None) -> str:
    """Return the optional GitHub link fragment (already escaped)."""
    if not github_url:
        return ""
    display = github_display or github_url
    return f" $|$\n    \\href{{{github_url}}}{{\\underline{{{display}}}}}"


# ---------------------------------------------------------------------------
# Build replacements dict from a formatted resume dict
# ---------------------------------------------------------------------------

def build_replacements(latex_resume: dict, *, summary: str = "") -> dict[str, str]:
    """Convert a LaTeX-formatted resume dict into a %%KEY%% → value mapping.

    *latex_resume* must already have been processed by ``format_for_latex``
    so every string is LaTeX-escaped.  *summary* is the AI-generated
    professional summary (also pre-escaped by the caller).
    """
    contact: dict = latex_resume.get("contact") or {}
    name: str = latex_resume.get("name") or ""

    linkedin_url: str = contact.get("linkedin") or ""
    linkedin_display: str = linkedin_url  # already escaped

    github_url: str = contact.get("github") or ""
    github_display: str = contact.get("github_display") or github_url

    return {
        "NAME": name,
        "PHONE": contact.get("phone") or "",
        "EMAIL": contact.get("email") or "",
        "LINKEDIN_URL": linkedin_url,
        "LINKEDIN_DISPLAY": linkedin_display,
        "GITHUB_BLOCK": _github_block(github_url, github_display),
        "PROFESSIONAL_SUMMARY": escape_latex(summary) if summary else "",
        "EDUCATION_ITEMS": _edu_items(latex_resume.get("education") or []),
        "EXPERIENCE_ITEMS": _exp_items(latex_resume.get("experience") or []),
        "PROJECT_ITEMS": _proj_items(latex_resume.get("projects") or []),
        "SKILLS_ITEMS": _skills_items(latex_resume.get("skills") or {}),
    }


# ---------------------------------------------------------------------------
# pdflatex compilation
# ---------------------------------------------------------------------------

def compile_latex(tex_source: str) -> bytes:
    """Compile *tex_source* string with pdflatex and return the PDF bytes.

    Raises ``RuntimeError`` if pdflatex is not found or compilation fails.
    """
    if not shutil.which("pdflatex"):
        raise RuntimeError(
            "pdflatex not found. Install TeX Live or MiKTeX and ensure pdflatex is on PATH."
        )

    with tempfile.TemporaryDirectory() as tmp:
        tex_file = Path(tmp) / "resume.tex"
        pdf_file = Path(tmp) / "resume.pdf"
        tex_file.write_text(tex_source, encoding="utf-8")

        result = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory", tmp,
                str(tex_file),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"pdflatex failed (exit {result.returncode}):\n{result.stdout[-3000:]}"
            )

        if not pdf_file.exists():
            raise RuntimeError("pdflatex reported success but PDF was not produced.")

        return pdf_file.read_bytes()


# ---------------------------------------------------------------------------
# Local filesystem save
# ---------------------------------------------------------------------------

def save_pdf(pdf_bytes: bytes, *, user_id: str, job_id: str) -> str:
    """Save *pdf_bytes* to the local filesystem and return the absolute path.

    Storage path: ``uploads/tailored/{user_id}/tailored_{job_id}.pdf``
    Re-runs overwrite the previous PDF.
    """
    out_dir = _OUTPUT_DIR / user_id
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"tailored_{job_id}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    return str(pdf_path)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_and_save(
    latex_resume: dict,
    *,
    user_id: str,
    job_id: str,
    summary: str = "",
) -> str:
    """Full pipeline: dict → LaTeX source → PDF → local filesystem → path.

    Parameters
    ----------
    latex_resume:
        Resume dict already processed by ``format_for_latex`` (strings escaped).
    user_id:
        User identifier (used for directory structure).
    job_id:
        Job identifier (used for filename).
    summary:
        AI-generated professional summary (plain text; this function escapes it).

    Returns
    -------
    str
        Absolute path of the saved PDF.
    """
    template_text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = build_replacements(latex_resume, summary=summary)
    tex_source = inject_into_template(template_text, replacements)
    pdf_bytes = compile_latex(tex_source)
    return save_pdf(pdf_bytes, user_id=user_id, job_id=job_id)
