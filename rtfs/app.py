from __future__ import annotations

import importlib
import json
import os
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import yarl
from litestar import Litestar, MediaType, Request, Response, get, post, status_codes
from litestar.di import Provide
from litestar.exceptions import NotAuthorizedException
from litestar.middleware import AbstractAuthenticationMiddleware, AuthenticationResult
from litestar.middleware.base import DefineMiddleware
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.datastructures import ResponseSpec
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.openapi.spec import Components, SecurityScheme
from litestar.response import Redirect

from ._types.results import RefreshResponse, Response as RTFSResponse
from .indexer import Indexes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from litestar.connection import ASGIConnection
    from litestar.datastructures import State

    from ._types.repo_config import RepoConfig


__all__ = ("APP",)

API_KEY_FILE = pathlib.Path("/run/secrets/api_key")
try:
    _token = API_KEY_FILE.read_text("utf8")
except FileNotFoundError:
    _token = os.getenv("API_KEY")
if not _token:
    raise RuntimeError("No API token has been provided.")
API_KEY = _token.rstrip()

REPO_PATH = pathlib.Path().parent / "repos.json"
if not REPO_PATH.exists():
    raise RuntimeError("Repo config file does not exist.")

REPO_CONFIG: dict[str, RepoConfig] = json.loads(REPO_PATH.read_text())
ACCEPTABLE_HOSTS: set[str] = {"github.com", "gitlab.com"}


@dataclass
class NewIndex:
    name: str
    directory: str  # name of the directory the source is located in
    url: str


class TokenAuthMiddleware(AbstractAuthenticationMiddleware):
    async def authenticate_request(self, connection: ASGIConnection[Any, Any, Any, Any]) -> AuthenticationResult:
        auth_header = connection.headers.get("Authorization")
        if not auth_header or auth_header != API_KEY:
            raise NotAuthorizedException

        return AuthenticationResult(user="Owner", auth=auth_header)


auth_middleware = DefineMiddleware(TokenAuthMiddleware)


def current_rtfs(state: State) -> Indexes:
    return state.rtfs


def _reload_indexer(config: dict[str, RepoConfig]) -> Indexes:
    module = importlib.import_module("rtfs.index")
    module = importlib.reload(module)

    return Indexes(REPO_CONFIG)


def _validate_url(url: str) -> bool:
    try:
        parsed = yarl.URL(url)
    except (ValueError, TypeError):
        return False

    # only accepted git hosts, only https and only one owner/repo
    return parsed.host in ACCEPTABLE_HOSTS and parsed.scheme == "https" and parsed.path.count("/") == 2


@get(
    path="/",
    dependencies={"rtfs": Provide(current_rtfs, sync_to_thread=False)},
    description="Get the source code from a library class or method.",
    name="RTFS",
    responses={
        200: ResponseSpec(data_container=RTFSResponse, description="Search results"),
        400: ResponseSpec(data_container=dict[Literal["error"], str], description="An error was found in your query."),
    },
)
async def get_rtfs(  # noqa: RUF029 # required in use of litestar callbacks
    rtfs: Indexes,
    search: str = "",
    library: str = "",
    direct: bool = False,  # noqa: FBT001, FBT002 # required for litestar callbacks
) -> Response[Mapping[str, Any]]:
    if not search and not library:
        return Redirect(path="/docs", status_code=status_codes.HTTP_303_SEE_OTHER)

    if not search:
        return Response(
            content={"error": "Missing `search` parameter"},
            media_type=MediaType.JSON,
            status_code=status_codes.HTTP_400_BAD_REQUEST,
        )

    result = rtfs.get_direct(library, search) if direct else rtfs.get_query(library, search)

    if result is None:
        return Response(
            content={
                "error": (
                    f"The library {library!r} cannot be found, "
                    "if you think this should be added then request it via `hyliantwink` on discord."
                ),
            },
            media_type=MediaType.JSON,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    return Response(content=result, media_type=MediaType.JSON, status_code=200)


@get(
    "/libraries",
    dependencies={"rtfs": Provide(current_rtfs, sync_to_thread=True)},
    description="List all available libraries within the tool.",
    name="RTFS Libraries",
    responses={200: ResponseSpec(data_container=dict[Literal["available_libraries"], dict[str, str | None]])},
    sync_to_thread=True,
    status_code=200,
)
def get_rtfs_libraries(rtfs: Indexes) -> Response[Mapping[str, Any]]:
    return Response(
        content={"available_libraries": rtfs.libraries},
        media_type=MediaType.JSON,
        status_code=status_codes.HTTP_202_ACCEPTED,
    )


@post(
    path="/refresh",
    middleware=[auth_middleware],
    description="Refresh the existing indexes with latest changes in their respective repositories",
    name="Refresh Indexes",
    responses={202: ResponseSpec(data_container=RefreshResponse, description="Results of the refresh")},
    security=[{"apiKey": []}],
    sync_to_thread=True,
    status_code=202,
)
def refresh_indexes(request: Request[str, str, State]) -> Response[RefreshResponse]:
    indexer = _reload_indexer(REPO_CONFIG)

    success = indexer.reload()
    request.state.rtfs = indexer

    return Response(
        content={"success": success, "commits": {name: value.commit for name, value in indexer.index.items()}},
        media_type=MediaType.JSON,
        status_code=status_codes.HTTP_202_ACCEPTED,
    )  # pyright: ignore[reportReturnType] # variance issues with `dict`


@post(
    path="/new",
    middleware=[auth_middleware],
    dependencies={"rtfs": Provide(current_rtfs, sync_to_thread=False)},
    description="Add a new repo to the index.",
    name="Add new repo to the index.",
    responses={
        201: ResponseSpec(data_container=RefreshResponse, description="Results of adding the new repo."),
        400: ResponseSpec(data_container=dict[Literal["error"], str], description="An error was found in your query."),
    },
    security=[{"apiKey": []}],
)
async def add_new_index(request: Request[str, str, State], data: NewIndex, rtfs: Indexes) -> Response[dict[str, Any]]:  # noqa: RUF029 # required for callback
    if data.name in REPO_CONFIG:
        return Response(content={"error": "Already tracking this repo."}, media_type=MediaType.JSON, status_code=400)

    if not _validate_url(data.url):
        return Response(
            content={"error": f"{data.url!r} is not a valid URL."},
            media_type=MediaType.JSON,
            status_code=400,
        )

    REPO_CONFIG[data.name] = {
        "repo_path": f"repos/{data.name.lower()}",
        "index_folder": data.directory,
        "repo_url": data.url,
    }

    indexer = _reload_indexer(REPO_CONFIG)
    success = indexer.reload()
    request.state.rtfs = indexer

    with REPO_PATH.open("w") as fp:
        json.dump(REPO_CONFIG, fp, indent=2)

    return Response(
        content={"success": success, "commits": {name: value.commit for name, value in indexer.index.items()}},
        media_type=MediaType.JSON,
        status_code=201,
    )


@get("/debug", dependencies={"rtfs": Provide(current_rtfs, sync_to_thread=False)}, status_code=200)
async def debug(rtfs: Indexes, library: str, path: str) -> Response[Mapping[str, Any]]:  # noqa: RUF029 # required for litestar callbacks
    item = rtfs.index[library].nodes
    resp = {name: repr(value) for name, value in item.items()}

    return Response(content=resp, media_type=MediaType.JSON, status_code=200)


def get_rtfs_indexes(app: Litestar) -> None:
    app.state.rtfs = Indexes(REPO_CONFIG)


def _bypass_for_owner(request: Request[Any, Any, Any]) -> bool:
    auth = request.headers.get("Authorization")
    if not auth:
        return True

    return auth != API_KEY


RL_CONFIG = RateLimitConfig(
    ("minute", 10),
    check_throttle_handler=_bypass_for_owner,
    rate_limit_limit_header_key="X-Ratelimit-Limit",
    rate_limit_policy_header_key="X-Ratelimit-Policy",
    rate_limit_remaining_header_key="X-Ratelimit-Remaining",
    rate_limit_reset_header_key="X-Ratelimit-Reset",
)

APP = Litestar(
    debug=False,
    route_handlers=[get_rtfs, get_rtfs_libraries, refresh_indexes, add_new_index],
    on_startup=[get_rtfs_indexes],
    middleware=[RL_CONFIG.middleware],
    openapi_config=OpenAPIConfig(
        title="RTFS",
        description="A small web api for providing the source code to library methods.",
        version="0.0.1",
        components=Components(
            security_schemes={
                "apiKey": SecurityScheme(
                    type="apiKey",
                    description="The owner/auth api key",
                    security_scheme_in="header",
                    name="Authorization",
                ),
            },
        ),
        render_plugins=[ScalarRenderPlugin()],
        path="/docs",
    ),
)
