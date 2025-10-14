from typing import NotRequired, TypedDict

__all__ = ("RepoConfig",)


class RepoConfig(TypedDict):
    repo_path: str
    index_folder: str
    repo_url: str
    aliases: NotRequired[list[str]]
