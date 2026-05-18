"""
Copy this file to app/config.py and fill in your values.
app/config.py is gitignored — each user has their own local copy.
"""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_keys: list[str] = []
    gemini_generation_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-2-preview"
    linkedin_li_at: str = ""
    linkedin_jsessionid: str = ""

    # Job search
    search_term: str = "Software Engineer"
    location: str = "Mountain View, CA"
    results_wanted: int = 100
    hours_old: int | None = 12
    distance: int = 50
    is_remote: bool = False
    job_type: str | None = "fulltime"            # fulltime | parttime | contract | internship
    experience_level: str | None = "entry level" # internship | entry level | associate | mid-senior level | director | executive
    blocked_companies: list[str] = []

    # Qualification
    min_fit_score: int = 80
    qualify_batch_size: int = 6

    # Google Sheets
    google_sheet_id: str = ""           # legacy-scraper production sheet
    smart_google_sheet_id: str = ""     # feature/local-app test sheet
    google_credentials_path: str = ""
    sheet_tab_name: str = "Jobs"
    status_on_scrape: str = "Have Not Applied"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("gemini_keys", mode="before")
    @classmethod
    def _parse_keys(cls, v):
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v

    @field_validator("blocked_companies", mode="before")
    @classmethod
    def _parse_blocked(cls, v):
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    def model_post_init(self, _ctx):
        if not self.gemini_keys:
            self.gemini_keys = [self.gemini_api_key]


settings = Settings()
