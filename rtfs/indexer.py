from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

from .index import Index

if TYPE_CHECKING:
    from ._types.repo_config import RepoConfig
    from ._types.results import Response

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

    def _load_config(self, config: dict[str, RepoConfig], /) -> None:
        self.__indexable = {k: Index(**v) for k, v in config.items()}

    def get_query(self, lib: str, query: str) -> Response | None:
        if not self._is_indexed:
            # todo, lock?
            raise RuntimeError("Indexing is not complete.")

        if lib not in self.index:
            return None

        start = time.monotonic()
        result = self.index[lib].find_matches(query)
        end = time.monotonic() - start
        return {
            "nodes": {x.name: {"source": x.source, "url": x.url} for x in result},
            "query_time": end,
            "commit": self.index[lib].commit,
        }

    def _do_pull(self, index: Index) -> bool:
        try:
            subprocess.run(["/bin/bash", "-c", f"cd {index.repo_path} && git pull"])
        except:
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
