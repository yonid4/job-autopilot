"""Streamlit UI for Job Autopilot. Thin layer over the FastAPI HTTP API.

Run the API first (`uvicorn app.main:app --reload`), then `streamlit run ui.py`.
"""
from __future__ import annotations

import os
from datetime import datetime

import requests
import streamlit as st

API_BASE = os.getenv("JOB_AUTOPILOT_API_URL", "http://localhost:8000")
STATUSES = ["not_applied", "applied", "interviewing", "offered", "rejected", "withdrawn"]


def _api(method: str, path: str, **kwargs):
    """Call the API. On any error, show it in the UI and return None."""
    try:
        resp = requests.request(method, f"{API_BASE}{path}", timeout=300, **kwargs)
    except requests.RequestException as exc:
        st.error(f"Cannot reach API at {API_BASE}: {exc}")
        return None
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        st.error(f"{method} {path} failed ({resp.status_code}): {detail}")
        return None
    if resp.status_code == 204 or not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


@st.dialog("Resume details", width="large")
def _resume_dialog(resume_id: str):
    st.markdown(
        "<style>div[data-testid='stDialog'] div[role='dialog']"
        "{width:92vw;max-width:1300px;}</style>",
        unsafe_allow_html=True,
    )
    detail = _api("GET", f"/api/v1/resumes/{resume_id}")
    if detail is None:
        return
    active = "yes" if detail["is_active"] else "no"
    st.write(f"**Label:** {detail['label']}  •  **Active:** {active}")
    parsed = detail.get("parsed_json")
    if not parsed:
        st.info("No parsed content yet — the resume may still be processing.")
        return

    for key in ("name", "email", "phone"):
        if parsed.get(key):
            st.write(f"**{key.title()}:** {parsed[key]}")
    if parsed.get("summary"):
        st.markdown("**Summary**")
        st.write(parsed["summary"])

    if parsed.get("skills"):
        st.markdown("**Skills**")
        st.write(", ".join(parsed["skills"]))

    if parsed.get("experience"):
        st.markdown("**Experience**")
        for e in parsed["experience"]:
            head = " — ".join(
                x for x in [e.get("title"), e.get("company"), e.get("duration")] if x
            )
            st.markdown(f"- **{head}**")
            if e.get("description"):
                st.write(e["description"])

    if parsed.get("education"):
        st.markdown("**Education**")
        for ed in parsed["education"]:
            degree = " ".join(y for y in [ed.get("degree"), ed.get("field")] if y)
            line = " — ".join(
                x for x in [degree, ed.get("school"), str(ed.get("graduation_year") or "")] if x
            )
            st.markdown(f"- {line}")

    if parsed.get("projects"):
        st.markdown("**Projects**")
        for p in parsed["projects"]:
            st.markdown(f"- **{p.get('name', '')}**")
            if p.get("description"):
                st.write(p["description"])
            tech = p.get("technologies")
            if tech:
                st.caption(", ".join(tech) if isinstance(tech, list) else str(tech))

    if parsed.get("certifications"):
        st.markdown("**Certifications**")
        for c in parsed["certifications"]:
            text = c if isinstance(c, str) else " — ".join(str(v) for v in c.values() if v)
            st.markdown(f"- {text}")


st.set_page_config(page_title="Job Autopilot", layout="wide")
st.title("Job Autopilot")
st.caption(f"API: {API_BASE}/docs")

tab_resumes, tab_jobs, tab_projects, tab_tailor, tab_apps = st.tabs(
    ["Resumes", "Jobs", "Projects", "Tailor", "Applications"]
)

# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------
with tab_resumes:
    st.subheader("Upload resume")
    up = st.file_uploader("PDF resume", type=["pdf"])
    label = st.text_input("Label", value="default")
    if st.button("Upload", disabled=up is None):
        res = _api(
            "POST",
            "/api/v1/resumes/upload",
            params={"label": label},
            files={"file": (up.name, up.getvalue(), "application/pdf")},
        )
        if res is not None:
            st.success(res.get("message", "Uploaded"))
            st.info("Parsing + embedding runs in the background — refresh shortly.")

    st.divider()
    st.subheader("Resumes")
    resumes = _api("GET", "/api/v1/resumes") or []
    if not resumes:
        st.caption("No resumes yet.")
    for r in resumes:
        c_label, c_view, c_active = st.columns([4, 1, 1])
        is_active = r["is_active"]
        badge = "**[active]** " if is_active else ""
        c_label.markdown(f'{badge}{r["label"]}  \n`{r["id"]}`')
        if c_view.button("View", key=f'rv_{r["id"]}'):
            _resume_dialog(r["id"])
        if is_active:
            c_active.button("Active", key=f'ra_{r["id"]}', disabled=True)
        elif c_active.button("Set active", key=f'rs_{r["id"]}'):
            res = _api("PATCH", f'/api/v1/resumes/{r["id"]}/active')
            if res is not None:
                st.success(f'"{r["label"]}" is now the active resume')
                st.rerun()

# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
with tab_jobs:
    st.subheader("Scrape LinkedIn")
    cfg = _api("GET", "/api/v1/config/scrape") or {}
    job_types = ["(any)", "fulltime", "parttime", "contract", "internship"]
    exp_levels = [
        "(any)", "internship", "entry level", "associate",
        "mid-senior level", "director", "executive",
    ]
    with st.form("scrape_cfg"):
        cfg_l, cfg_r = st.columns(2)
        with cfg_l:
            f_term = st.text_input("Search term", value=cfg.get("search_term", ""))
            f_location = st.text_input("Location", value=cfg.get("location", ""))
            f_results = st.number_input(
                "Results wanted", min_value=1, max_value=1000,
                value=int(cfg.get("results_wanted", 100)),
            )
            f_hours = st.number_input(
                "Posted within (hours)", min_value=1, max_value=720,
                value=int(cfg.get("hours_old") or 24),
            )
            f_distance = st.number_input(
                "Distance (miles)", min_value=0, max_value=200,
                value=int(cfg.get("distance", 50)),
            )
        with cfg_r:
            jt = cfg.get("job_type") or "(any)"
            f_jobtype = st.selectbox(
                "Job type", job_types,
                index=job_types.index(jt) if jt in job_types else 0,
            )
            el = cfg.get("experience_level") or "(any)"
            f_exp = st.selectbox(
                "Experience level", exp_levels,
                index=exp_levels.index(el) if el in exp_levels else 0,
            )
            f_remote = st.checkbox("Remote only", value=bool(cfg.get("is_remote", False)))
            f_minscore = st.slider(
                "Min fit score (sheet push)", 0, 100, int(cfg.get("min_fit_score", 80))
            )
            f_batch = st.number_input(
                "Qualify batch size", min_value=1, max_value=50,
                value=int(cfg.get("qualify_batch_size", 6)),
            )
        f_blocked = st.text_input(
            "Blocked companies (comma-separated)",
            value=", ".join(cfg.get("blocked_companies", [])),
        )
        _auto_tab = f"{datetime.now():%b} {datetime.now().day}"
        f_sheet_tab = st.text_input(
            "Sheet page name",
            value=cfg.get("sheet_tab_name", ""),
            placeholder=_auto_tab,
            help=f"Google Sheet tab to write to. Leave empty to use today's date (e.g. \"{_auto_tab}\").",
        )
        if st.form_submit_button("Run scrape (background)"):
            sheet_tab = f_sheet_tab.strip() or f"{datetime.now():%b} {datetime.now().day}"
            payload = {
                "search_term": f_term,
                "location": f_location,
                "results_wanted": int(f_results),
                "hours_old": int(f_hours),
                "distance": int(f_distance),
                "is_remote": f_remote,
                "job_type": None if f_jobtype == "(any)" else f_jobtype,
                "experience_level": None if f_exp == "(any)" else f_exp,
                "blocked_companies": [c.strip() for c in f_blocked.split(",") if c.strip()],
                "min_fit_score": int(f_minscore),
                "qualify_batch_size": int(f_batch),
                "sheet_tab_name": sheet_tab,
            }
            res = _api("POST", "/api/v1/jobs/scrape", json=payload)
            if res is not None:
                st.success(res.get("message", "Scrape started"))
                st.info("Runs in the background — refresh the list below shortly.")

    st.divider()
    col_url, col_manual = st.columns(2)
    with col_url:
        st.subheader("Ingest by URL")
        with st.form("ingest_url"):
            url = st.text_input("LinkedIn job URL")
            if st.form_submit_button("Ingest") and url:
                res = _api("POST", "/api/v1/jobs/ingest", json={"url": url})
                if res is not None:
                    verb = "created" if res["created"] else "already existed"
                    st.success(f"Job {verb}: {res['job_id']}")
    with col_manual:
        st.subheader("Add manually")
        with st.form("manual_job"):
            m_url = st.text_input("URL")
            m_title = st.text_input("Title")
            m_company = st.text_input("Company")
            m_desc = st.text_area("Description")
            m_salary = st.text_input("Salary")
            m_level = st.text_input("Job level")
            if st.form_submit_button("Add"):
                payload = {
                    "url": m_url,
                    "title": m_title,
                    "company": m_company,
                    "description": m_desc or None,
                    "salary": m_salary or None,
                    "job_level": m_level or None,
                }
                res = _api("POST", "/api/v1/jobs/manual", json=payload)
                if res is not None:
                    verb = "created" if res["created"] else "already existed"
                    st.success(f"Job {verb}: {res['job_id']}")

    st.divider()
    st.subheader("Jobs")
    limit = st.slider("Limit", 1, 200, 50)
    jobs = _api("GET", "/api/v1/jobs", params={"limit": limit}) or []
    if jobs:
        st.dataframe(
            [
                {
                    "title": j["title"],
                    "company": j["company"],
                    "level": j.get("job_level"),
                    "salary": j.get("salary"),
                    "url": j["url"],
                    "id": j["id"],
                }
                for j in jobs
            ],
            use_container_width=True,
        )
    else:
        st.caption("No jobs yet.")

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
with tab_projects:
    st.subheader("Add project")
    with st.form("add_project"):
        p_name = st.text_input("Name")
        p_desc = st.text_area("Description")
        p_tech = st.text_input("Technologies (comma-separated)")
        p_url = st.text_input("URL")
        if st.form_submit_button("Add"):
            payload = {
                "name": p_name,
                "description": p_desc,
                "technologies": [t.strip() for t in p_tech.split(",") if t.strip()],
                "url": p_url or None,
            }
            res = _api("POST", "/api/v1/projects", json=payload)
            if res is not None:
                st.success(f"Added project: {res['name']}")

    st.divider()
    st.subheader("Projects")
    projects = _api("GET", "/api/v1/projects") or []
    if projects:
        st.dataframe(
            [
                {
                    "name": p["name"],
                    "technologies": ", ".join(p["technologies"]),
                    "url": p.get("url"),
                    "id": p["id"],
                }
                for p in projects
            ],
            use_container_width=True,
        )
    else:
        st.caption("No projects yet.")

# ---------------------------------------------------------------------------
# Tailor
# ---------------------------------------------------------------------------
with tab_tailor:
    st.subheader("Tailor for a job")
    jobs = _api("GET", "/api/v1/jobs", params={"limit": 200}) or []
    resumes = _api("GET", "/api/v1/resumes") or []
    if not jobs:
        st.caption("Ingest a job first.")
    else:
        job_map = {f'{j["title"]} - {j["company"]}': j["id"] for j in jobs}
        job_label = st.selectbox("Job", list(job_map))

        resume_map = {"(active resume)": None}
        for r in resumes:
            tag = " *active" if r["is_active"] else ""
            resume_map[f'{r["label"]}{tag}'] = r["id"]
        resume_label = st.selectbox("Resume", list(resume_map))

        payload = {"job_id": job_map[job_label]}
        if resume_map[resume_label]:
            payload["resume_id"] = resume_map[resume_label]

        col_full, col_res, col_cl = st.columns(3)
        action = None
        if col_full.button("Full"):
            action = "/api/v1/tailor/full"
        if col_res.button("Resume only"):
            action = "/api/v1/tailor/resume"
        if col_cl.button("Cover letter only"):
            action = "/api/v1/tailor/cover-letter"

        if action:
            with st.spinner("Calling Gemini - this can take a bit"):
                res = _api("POST", action, json=payload)
            if res is not None:
                st.session_state["last_tailor"] = res

        result = st.session_state.get("last_tailor")
        if result:
            st.divider()
            if result.get("fit_score") is not None:
                st.metric("Fit score", result["fit_score"])
            if result.get("strengths"):
                st.markdown("**Strengths**")
                for s in result["strengths"]:
                    st.markdown(f"- {s}")
            if result.get("gaps"):
                st.markdown("**Gaps**")
                for g in result["gaps"]:
                    st.markdown(f"- {g}")
            if result.get("summary_text"):
                st.markdown("**Tailored summary**")
                st.text_area(
                    "summary", result["summary_text"], height=140, label_visibility="collapsed"
                )
            if result.get("cover_letter"):
                st.markdown("**Cover letter**")
                st.text_area(
                    "cover_letter",
                    result["cover_letter"],
                    height=320,
                    label_visibility="collapsed",
                )

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
with tab_apps:
    st.subheader("Applications")
    flt = st.selectbox(
        "Filter by status", ["(all)"] + STATUSES, format_func=lambda s: s
    )
    params = None if flt == "(all)" else {"status": flt}
    apps = _api("GET", "/api/v1/applications", params=params) or []
    if not apps:
        st.caption("No applications yet — run tailoring on a job.")
    for a in apps:
        score = a.get("fit_score")
        header = f'{a["status"]} | fit {score if score is not None else "-"} | job {a["job_id"]}'
        with st.expander(header):
            if a.get("summary_text"):
                st.markdown("**Summary**")
                st.write(a["summary_text"])
            if a.get("cover_letter"):
                st.markdown("**Cover letter**")
                st.text_area(
                    "cl",
                    a["cover_letter"],
                    height=240,
                    label_visibility="collapsed",
                    key=f"cl_{a['id']}",
                )
            idx = STATUSES.index(a["status"]) if a["status"] in STATUSES else 0
            new_status = st.selectbox("Status", STATUSES, index=idx, key=f"st_{a['id']}")
            if st.button("Update", key=f"upd_{a['id']}"):
                res = _api(
                    "PATCH",
                    f'/api/v1/applications/{a["id"]}/status',
                    json={"status": new_status},
                )
                if res is not None:
                    st.success("Updated")
                    st.rerun()
