from __future__ import annotations

import importlib
import json
import os
import pathlib
from typing import TYPE_CHECKING, Any

from litestar import Litestar, MediaType, Request, Response, get, post, status_codes
from litestar.di import Provide
from litestar.exceptions import NotAuthorizedException
from litestar.middleware import AbstractAuthenticationMiddleware, AuthenticationResult
from litestar.middleware.base import DefineMiddleware
from litestar.middleware.rate_limit import RateLimitConfig

from .indexer import Indexes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from litestar.connection import ASGIConnection
    from litestar.datastructures import State

    from ._types.repo_config import RepoConfig

__all__ = ("APP",)

OWNER_TOKEN = os.getenv("API_TOKEN")
if not OWNER_TOKEN:
    raise RuntimeError("Sorry, we required an `API_TOKEN` environment variable to be present.")

REPO_PATH = pathlib.Path().parent / "repos.json"
if not REPO_PATH.exists():
    raise RuntimeError("Repo config file does not exist.")

REPO_CONFIG: dict[str, RepoConfig] = json.loads(REPO_PATH.read_text())


class TokenAuthMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(self, connection: ASGIConnection[Any, Any, Any, Any]) -> AuthenticationResult:
        auth_header = connection.headers.get("Authorization")
        if not auth_header or auth_header != OWNER_TOKEN:
            raise NotAuthorizedException()

        return AuthenticationResult(user="Owner", auth=auth_header)


auth_middleware = DefineMiddleware(TokenAuthMiddleware)


def current_rtfs(state: State) -> Indexes:
    return state.rtfs


@get(path="/", dependencies={"rtfs": Provide(current_rtfs, sync_to_thread=False)})
async def get_rtfs(query: dict[str, str], rtfs: Indexes) -> Response[Mapping[str, Any]]:
    query_search = query.get("search")
    library = query.get("library", "").lower()
    format_ = query.get("format", "url")

    if not query_search or not library:
        return Response(content={"available_libraries": rtfs.libraries}, media_type=MediaType.JSON, status_code=200)
    elif not query_search:
        return Response({"error": "Missing `search` query parameter."}, media_type=MediaType.JSON, status_code=400)
    elif not library:
        return Response({"error": "Missing `library` query parameter."}, media_type=MediaType.JSON, status_code=400)

    if format_ not in ("url", "source"):
        return Response(
            {"error": "The `format` parameter must be `url` or `source`."}, media_type=MediaType.JSON, status_code=400
        )

    result = rtfs.get_query(library, query_search)
    if result is None:
        return Response(
            content={
                "error": f"The library {library!r} cannot be found, if you think this should be added then request it via `hyliantwink` on discord."
            },
            media_type=MediaType.JSON,
            status_code=status_codes.HTTP_418_IM_A_TEAPOT,
        )

    return Response(content=result, media_type=MediaType.JSON, status_code=200)


@post(path="/refresh", middleware=[auth_middleware], dependencies={"rtfs": Provide(current_rtfs, sync_to_thread=False)})
async def refresh_indexes(request: Request[str, str, State], rtfs: Indexes) -> Response[dict[str, Any]]:
    module = importlib.import_module("rtfs.node")
    module = importlib.reload(module)

    indexer = Indexes(REPO_CONFIG)
    success = indexer.reload()
    request.state.rtfs = indexer

    return Response(
        content={"success": success, "commits": {name: value.commit for name, value in indexer.index.items()}},
        media_type=MediaType.JSON,
        status_code=202,
    )


def get_rtfs_indexes(app: Litestar) -> None:
    app.state.rtfs = Indexes(REPO_CONFIG)


def _bypass_for_owner(request: Request[Any, Any, Any]) -> bool:
    auth = request.headers.get("Authorization")
    if not auth:
        return True

    if auth == OWNER_TOKEN:
        return False

    return True


RL_CONFIG = RateLimitConfig(
    ("minute", 10),
    check_throttle_handler=_bypass_for_owner,
    rate_limit_limit_header_key="X-Ratelimit-Limit",
    rate_limit_policy_header_key="X-Ratelimit-Policy",
    rate_limit_remaining_header_key="X-Ratelimit-Remaining",
    rate_limit_reset_header_key="X-Ratelimit-Reset",
)

APP = Litestar(route_handlers=[get_rtfs, refresh_indexes], on_startup=[get_rtfs_indexes], middleware=[RL_CONFIG.middleware])
