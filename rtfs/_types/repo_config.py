from typing import TypedDict

__all__ = ("RepoConfig",)


class RepoConfig(TypedDict):
    repo_path: str
    index_folder: str
    repo_url: str
