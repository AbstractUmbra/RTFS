from typing import TypedDict

__all__ = ("Response",)


class NodeResponse(TypedDict):
    source: str
    url: str


class Response(TypedDict):
    nodes: dict[str, NodeResponse]
    query_time: float
    commit: str | None
