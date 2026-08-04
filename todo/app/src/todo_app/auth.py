"""Authentication: HA Ingress requests are trusted, everything else needs a bearer token."""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request

# Home Assistant's ingress proxy always connects from this address inside
# the add-on network, and HA has already authenticated the user.
HA_INGRESS_IP = "172.30.32.2"


def api_token() -> str:
    return os.environ.get("TODO_API_TOKEN", "")


def is_ingress_request(request: Request) -> bool:
    return request.client is not None and request.client.host == HA_INGRESS_IP


def require_auth(request: Request) -> None:
    """FastAPI dependency guarding API and web routes.

    Accepts, in order: HA ingress origin, bearer header (CLI/API),
    ?token= query param or cookie (browser on the LAN — the middleware in
    main.py turns a valid query param into a persistent cookie).
    """
    if is_ingress_request(request):
        return
    token = api_token()
    if not token:
        raise HTTPException(status_code=403, detail="LAN access disabled: no api_token configured")
    header = request.headers.get("authorization", "")
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() == "bearer" and secrets.compare_digest(credentials, token):
        return
    for candidate in (request.query_params.get("token"), request.cookies.get("todo_token")):
        if candidate and secrets.compare_digest(candidate, token):
            return
    raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
