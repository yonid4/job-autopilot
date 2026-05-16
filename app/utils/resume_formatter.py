from __future__ import annotations

import re as _re

_LATEX_MAP = {
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
}
# Single-pass regex: match any of the 10 specials and replace in one sweep
# so no replacement string is ever re-scanned.
_LATEX_RE = _re.compile(r"[\\&%$#_{}\~\^]")


def escape_latex(text: str) -> str:
    """Escape all 10 LaTeX special characters in *text* in a single pass."""
    return _LATEX_RE.sub(lambda m: _LATEX_MAP[m.group()], text)


def _escape_leaves(obj: object) -> object:
    """Recursively escape every string leaf in a nested dict/list."""
    if isinstance(obj, str):
        return escape_latex(obj)
    if isinstance(obj, dict):
        return {k: _escape_leaves(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_escape_leaves(item) for item in obj]
    return obj


def format_for_frontend(
    rewritten_json: dict,
    *,
    fit_score: int | None = None,
    summary: str | None = None,
    cover_letter: str | None = None,
    hook_project_id: str | None = None,
    section_order_suggestion: str | None = None,
) -> dict:
    """Return the full resume dict with metadata fields attached.

    Bullet objects ``{"original": ..., "tailored": ...}`` are passed through as-is.
    """
    result = dict(rewritten_json)
    result["fit_score"] = fit_score
    result["summary"] = summary
    result["cover_letter"] = cover_letter
    result["hook_project_id"] = hook_project_id
    result["section_order_suggestion"] = section_order_suggestion
    return result


def _latex_process(obj: object) -> object:
    """Recursively process a resume structure for LaTeX output.

    For bullet objects ``{"original": ..., "tailored": ...}``, keeps only the
    ``tailored`` value and escapes it. All other string leaves are escaped.
    """
    if isinstance(obj, dict):
        if "original" in obj and "tailored" in obj:
            return escape_latex(str(obj["tailored"]))
        return {k: _latex_process(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_latex_process(item) for item in obj]
    if isinstance(obj, str):
        return escape_latex(obj)
    return obj


def format_for_latex(rewritten_json: dict) -> dict:
    """Return resume dict ready for LaTeX injection.

    Every string leaf is LaTeX-escaped. For bullet objects
    ``{"original": ..., "tailored": ...}``, only ``tailored`` is kept and escaped;
    ``original`` is dropped.
    """
    return _latex_process(rewritten_json)  # type: ignore[return-value]
