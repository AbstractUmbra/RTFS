from __future__ import annotations

import logging
import subprocess  # noqa: S404 # accepted use
import time
from typing import TYPE_CHECKING

from .index import Index

if TYPE_CHECKING:
    from ._types.repo_config import RepoConfig
    from ._types.results import Response
    from .index import Node

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)


class Indexes:
    __indexable: dict[str, Index]

    def __init__(self, config: dict[str, RepoConfig], /) -> None:
        self.index: dict[str, Index] = {}
        self._is_indexed: bool = False
        self._load_config(config)
        self._do_index()

    @property
    def indexed(self) -> bool:
        return self._is_indexed

    @property
    def libraries(self) -> dict[str, str | None]:
        return {lib: index.version for lib, index in self.__indexable.items()}

    def _extract_node_from_long_name(self, lib: str, name: str) -> Node:
        nodes = self.index[lib].nodes

        for node in nodes.values():
            if node.full_name == name:
                return node
        msg = f"No node by the name of {name!r} found in library {lib!r}."
        raise ValueError(msg)

    def _load_config(self, config: dict[str, RepoConfig], /) -> None:
        self.__indexable = {k: Index(library=k, **v) for k, v in config.items()}

    def get_query(self, lib: str, query: str) -> Response | None:
        if not self._is_indexed:
            raise RuntimeError("Indexing is not complete.")

        if lib not in self.index:
            return None

        start = time.monotonic()
        result = self.index[lib].find_matches(query)
        end = time.monotonic() - start
        return {
            "results": {x.short_name: {"source": x.source, "url": x.url} for x in result},
            "query_time": end,
            "commit_sha": self.index[lib].commit,
        }

    def get_direct(self, lib: str, query: str) -> Response | None:
        if not self._is_indexed:
            raise RuntimeError("Indexing is not complete.")

        if lib not in self.index:
            return None

        start = time.monotonic()
        try:
            result = self.index[lib].nodes.get(query) or self._extract_node_from_long_name(lib, query)
        except ValueError:
            result = None
        end = time.monotonic() - start

        return {
            "results": {result.short_name: {"source": result.source, "url": result.url}} if result else None,
            "query_time": end,
            "commit_sha": self.index[lib].commit,
        }

    def _do_pull(self, index: Index) -> bool:
        try:
            subprocess.run(["/bin/bash", "-c", f"cd {index.repo_path} && git pull"], check=False)  # noqa: S603 # trusted input
        except (ValueError, subprocess.CalledProcessError):
            return False

        return True

    def _do_index(self) -> None:
        LOGGER.info("Starting indexing.")

        amount = len(self.__indexable)

        for idx, (name, index) in enumerate(self.__indexable.items(), start=1):
            LOGGER.info("Indexing module %r (%s/%s)", name, idx, amount)

            self.index[name] = index
            index.index_lib()
            LOGGER.info("Finished indexing module %r (%s nodes)", name, len(index.nodes))

        LOGGER.info("Indexing complete!")
        self._is_indexed = True

    def reload(self) -> bool:
        self._is_indexed = False
        success: list[str] = []
        for name, value in self.__indexable.items():
            if self._do_pull(value):
                success.append(name)

        self._do_index()

        return len(success) == len(self.__indexable)
