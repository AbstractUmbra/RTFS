from typing import TypedDict

__all__ = ("Response",)


class NodeResponse(TypedDict):
    source: str
    url: str


class Response(TypedDict):
    results: dict[str, NodeResponse]
    query_time: float
    commit_sha: str | None
