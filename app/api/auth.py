from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import settings

_bearer = HTTPBearer()

# JWKS client for ES256 tokens (Supabase newer projects)
_jwks_client = PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Verify Supabase JWT (ES256 or HS256) and return the user's UUID."""
    token = credentials.credentials

    # Detect algorithm from token header — allowlist only known algorithms
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")

    _SYMMETRIC_ALGS = {"HS256"}
    _ASYMMETRIC_ALGS = {"ES256", "RS256"}
    _ALLOWED_ALGS = _SYMMETRIC_ALGS | _ASYMMETRIC_ALGS

    if alg not in _ALLOWED_ALGS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported signing algorithm: {alg}",
        )

    try:
        if alg in _SYMMETRIC_ALGS:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            # ES256 / RS256 — fetch signing key from JWKS
            signing_key = _jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing sub claim")

    return user_id
