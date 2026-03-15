"""Shared pytest fixtures and environment setup.

This module is loaded before any test file is collected, so we can patch
required environment variables here to prevent Settings() from failing when
there is no .env file present (e.g. CI, unit test runs).
"""
from __future__ import annotations

import os

# Provide stub values for all required settings so app.config.Settings() can
# instantiate without a .env file.  Individual tests that exercise real
# integrations should override these via their own fixtures.
_REQUIRED_STUBS = {
    "SUPABASE_URL": "https://stub.supabase.co",
    "SUPABASE_ANON_KEY": "stub-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "stub-service-role-key",
    "SUPABASE_JWT_SECRET": "stub-jwt-secret",
    "GEMINI_API_KEY": "stub-gemini-key",
}

for key, value in _REQUIRED_STUBS.items():
    os.environ.setdefault(key, value)
