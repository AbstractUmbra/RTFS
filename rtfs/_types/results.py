from typing import TypedDict

__all__ = ("RefreshResponse", "Response")


class NodeResponse(TypedDict):
    source: str
    url: str


class Response(TypedDict):
    results: dict[str, NodeResponse] | None
    query_time: float
    commit_sha: str | None


class RefreshResponse(TypedDict):
    success: bool
    commits: dict[str, str]
