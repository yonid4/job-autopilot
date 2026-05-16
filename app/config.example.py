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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("gemini_keys", mode="before")
    @classmethod
    def _parse_keys(cls, v):
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v

    def model_post_init(self, _ctx):
        if not self.gemini_keys:
            self.gemini_keys = [self.gemini_api_key]


settings = Settings()
