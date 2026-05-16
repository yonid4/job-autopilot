"""Shared pytest fixtures and environment setup.

This module is loaded before any test file is collected, so we can patch
required environment variables here to prevent Settings() from failing when
there is no .env file present (e.g. CI, unit test runs).
"""
from __future__ import annotations

import os

os.environ.setdefault("GEMINI_API_KEY", "stub-gemini-key")
