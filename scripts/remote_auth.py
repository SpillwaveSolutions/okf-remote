#!/usr/bin/env python3
"""OAuth 2.1 / OIDC resource-server helpers. Token validation only.

Issuer, audience, and JWKS come from the environment. This module does not
issue tokens. Binding a network interface without an issuer is a startup error.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def b64url_decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def env_config() -> dict:
    return {
        "issuer": (os.environ.get("OKF_MCP_ISSUER") or "").strip(),
        "audience": (os.environ.get("OKF_MCP_AUDIENCE") or "").strip(),
        "jwks": (os.environ.get("OKF_MCP_JWKS") or "").strip(),
    }


def require_bind_config() -> dict:
    cfg = env_config()
    if not cfg["issuer"]:
        raise AuthError("binding without a configured issuer is a startup error (OKF_MCP_ISSUER)", status=1)
    if not cfg["audience"]:
        raise AuthError("OKF_MCP_AUDIENCE required when binding", status=1)
    if not cfg["jwks"]:
        raise AuthError("OKF_MCP_JWKS required when binding (URL or file path)", status=1)
    return cfg


def load_jwks(spec: str) -> dict:
    if spec.startswith("http://") or spec.startswith("https://"):
        with urllib.request.urlopen(spec, timeout=5) as resp:  # noqa: S310 — operator-configured JWKS
            return json.loads(resp.read().decode("utf-8"))
    return json.loads(Path(spec).expanduser().read_text(encoding="utf-8"))


def _find_key(jwks: dict, header: dict) -> dict | None:
    kid = header.get("kid")
    alg = header.get("alg")
    for key in jwks.get("keys") or []:
        if kid and key.get("kid") != kid:
            continue
        if alg and key.get("alg") and key.get("alg") != alg:
            continue
        return key
    return None


def _verify_hs256(signing_input: bytes, sig: bytes, key: dict) -> None:
    k = key.get("k")
    if not k:
        raise AuthError("oct key missing k")
    secret = b64url_decode(k)
    expected = hmac.new(secret, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        raise AuthError("invalid token signature")


def _verify_rs256(signing_input: bytes, sig: bytes, key: dict) -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        from cryptography.hazmat.primitives import hashes
    except ImportError as exc:
        raise AuthError("RS256 requires the cryptography package") from exc
    n = int.from_bytes(b64url_decode(key["n"]), "big")
    e = int.from_bytes(b64url_decode(key["e"]), "big")
    pub = RSAPublicNumbers(e, n).public_key()
    try:
        pub.verify(sig, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:  # noqa: BLE001 — map any verify failure to 401
        raise AuthError("invalid token signature") from exc


def validate_token(token: str, cfg: dict | None = None) -> dict:
    cfg = cfg or env_config()
    if not token:
        raise AuthError("missing bearer token")
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("malformed token")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(b64url_decode(header_b64))
        payload = json.loads(b64url_decode(payload_b64))
        sig = b64url_decode(sig_b64)
    except Exception as exc:  # noqa: BLE001
        raise AuthError("malformed token") from exc
    iss = payload.get("iss")
    if cfg["issuer"] and iss != cfg["issuer"]:
        raise AuthError("token issuer mismatch")
    aud = payload.get("aud")
    audience = cfg["audience"]
    if audience:
        if isinstance(aud, list):
            if audience not in aud:
                raise AuthError("token audience mismatch")
        elif aud != audience:
            raise AuthError("token audience mismatch")
    exp = payload.get("exp")
    if exp is not None and time.time() > float(exp):
        raise AuthError("token expired")
    nbf = payload.get("nbf")
    if nbf is not None and time.time() < float(nbf):
        raise AuthError("token not yet valid")
    jwks = load_jwks(cfg["jwks"]) if cfg.get("jwks") else {"keys": []}
    key = _find_key(jwks, header)
    if not key:
        raise AuthError("no matching JWKS key")
    alg = header.get("alg")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    if alg == "HS256":
        _verify_hs256(signing_input, sig, key)
    elif alg == "RS256":
        _verify_rs256(signing_input, sig, key)
    else:
        raise AuthError(f"unsupported alg: {alg}")
    return payload
