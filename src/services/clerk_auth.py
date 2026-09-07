from __future__ import annotations

from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from src.config import get_settings


class ClerkAuthenticationError(ValueError):
    pass


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def verify_clerk_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.clerk_issuer or not settings.clerk_jwks_url:
        raise ClerkAuthenticationError("Clerk issuer and JWKS URL are not configured")
    try:
        key = _jwks_client(settings.clerk_jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise ClerkAuthenticationError("Invalid Clerk session token") from exc

    authorized = {item.strip() for item in settings.clerk_authorized_parties.split(",") if item.strip()}
    authorized_party = claims.get("azp")
    if authorized and authorized_party and authorized_party not in authorized:
        raise ClerkAuthenticationError("Clerk token was issued to an unauthorized party")
    if claims.get("sts") == "pending":
        raise ClerkAuthenticationError("Clerk session setup is incomplete")
    return claims


def actor_profile_from_claims(claims: dict[str, Any]) -> dict[str, str | None]:
    return {
        "actor_id": str(claims["sub"]),
        "display_name": claims.get("name") or claims.get("full_name") or str(claims["sub"]),
        "email": claims.get("email") or claims.get("email_address"),
        "image_url": claims.get("image_url") or claims.get("picture"),
    }
