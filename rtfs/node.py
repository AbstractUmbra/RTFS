__all__ = ("Node",)


import ast
import configparser
import difflib
import logging
import os
import pathlib
import re
import subprocess
import time
from typing import Any, ClassVar

from yarl import URL

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
VERSION_REGEX = re.compile(r"__version__\s*=\s*(?:'|\")((?:\w|\.)*)(?:'|\")")


def _get_attr_name(attr: ast.Attribute) -> str | None:
    if type(attr.value) is ast.Attribute:
        return _get_attr_name(attr.value)


class Node:
    __slots__ = (
        "file",
        "line",
        "end_line",
        "name",
        "url",
        "source",
    )

    def __init__(
        self,
        *,
        file: str | None,
        line: int,
        end_line: int | None,
        name: str,
        url: str | None,
        source: str,
    ) -> None:
        self.file = file
        self.line = line
        self.end_line = end_line
        self.name = name
        self.url = url
        self.source = source

    def __repr__(self) -> str:
        return f"<Node file={self.file} line={self.line} end_line={self.end_line} name={self.name} url={self.url}>"


class Index:
    __slots__ = (
        "repo_path",
        "index_folder",
        "repo_url",
        "version",
        "branch",
        "commit",
        "nodes",
        "keys",
    )

    def __init__(
        self,
        repo_path: str,
        /,
        *,
        index_folder: str,
        repo_url: str,
        branch: str | None = None,
        version: str | None = None,
    ) -> None:
        self.repo_path: pathlib.Path = pathlib.Path() / repo_path

        if index_folder in ("", ".", "./"):
            self.index_folder = ""
        else:
            self.index_folder = index_folder

        self.repo_url: URL = URL(repo_url)
        self.version: str | None = version

        if not self.repo_path.exists():
            self._clone_repo(self.repo_url, self.repo_path, branch)

        self.branch = self._process_git_dir()
        self.commit = self._process_current_commit()

        self.nodes: dict[str, Node] = {}
        self.keys: list[str] = []

    def _clone_repo(self, url: URL, path: pathlib.Path, branch_name: str | None) -> None:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)

        proc = ["git", "clone", str(url), str(self.repo_path)]
        branch = ["&&", "git", "checkout", branch_name] if branch_name else []

        proc.extend(branch)

        subprocess.run(proc)

    def _process_git_dir(self) -> str:
        git_path = self.repo_path / ".git"
        if not git_path.exists():
            raise ValueError(f"{self.repo_path} does not appear to be a valid git directory.")

        head_path = git_path / "HEAD"
        current_branch = head_path.read_text("utf-8").rsplit("/")[-1]

        if not current_branch:
            return self._process_git_config()

        return current_branch.strip()

    def _process_git_config(self) -> str:
        git_config_path = self.repo_path / ".git" / "config"
        if not git_config_path.exists():
            raise ValueError(f"{self.repo_path} does not appear to be a valid git directory.")

        config = configparser.ConfigParser()
        config.read_string(git_config_path.read_text("utf-8"))

        return config.get('remote "origin"', "fetch").split("/")[-1].strip()

    def _process_current_commit(self) -> str | None:
        ref_path = self.repo_path / ".git" / "refs" / "heads" / self.branch
        if not ref_path.exists():
            return None

        return ref_path.read_text().strip()

    def index_class_function(
        self,
        nodes: dict[str, Node],
        cls: ast.ClassDef,
        src: list[str],
        func: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        class_name = cls.name

        for body_part in func.body:
            if type(body_part) is ast.Assign:
                target_0 = body_part.targets[0]
                func_args = [
                    *func.args.posonlyargs,
                    *func.args.args,
                    *func.args.kwonlyargs,
                ]
                if type(target_0) is ast.Attribute and _get_attr_name(target_0) == func_args[0].arg:
                    name = class_name + "." + target_0.attr
                    if name not in nodes:
                        nodes[name] = Node(
                            file=None,
                            line=body_part.lineno,
                            end_line=body_part.end_lineno,
                            name=name,
                            url=None,
                            source="\n".join(src[body_part.lineno - 1 : body_part.end_lineno]),
                        )

    def index_class(self, *, nodes: dict[str, Node], src: list[str], cls: ast.ClassDef) -> None:
        class_name = cls.name

        for body_part in cls.body:
            if isinstance(body_part, ast.Assign):
                target = body_part.targets[0]
                assert isinstance(target, ast.Name)

                if not target.id.startswith("__"):
                    name = class_name + "." + target.id
                    if name not in nodes:
                        nodes[name] = Node(
                            file=None,
                            line=body_part.lineno,
                            end_line=body_part.end_lineno,
                            name=name,
                            url=None,
                            source="\n".join(src[body_part.lineno - 1 : body_part.end_lineno]),
                        )
            elif isinstance(body_part, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not body_part.name.startswith("__"):
                    name = class_name + "." + body_part.name
                    nodes[name] = Node(
                        file=None,
                        line=body_part.lineno,
                        end_line=body_part.end_lineno,
                        name=name,
                        url=None,
                        source="\n".join(src[body_part.lineno - 1 : body_part.end_lineno]),
                    )
                self.index_class_function(nodes, cls, src, body_part)

    def index_file(self, nodes: dict[str, Node], fp: pathlib.Path, dirs: list[str], is_utils: bool = False) -> None:
        inner_nodes: dict[str, Node] = {}

        opened = fp.read_text("utf-8")

        lines = opened.split("\n")
        node = ast.parse(opened)

        for body in node.body:
            if isinstance(body, ast.ClassDef):
                inner_nodes[body.name] = Node(
                    file=None,
                    line=body.lineno,
                    end_line=body.end_lineno,
                    name=body.name,
                    url=None,
                    source="\n".join(lines[body.lineno - 1 : body.end_lineno]),
                )
                self.index_class(nodes=inner_nodes, src=lines, cls=body)
            elif isinstance(body, ast.Assign) and isinstance(body.targets[0], ast.Name):
                name = body.targets[0].id
                if name not in inner_nodes:
                    inner_nodes[name] = Node(
                        file=None,
                        line=body.lineno,
                        end_line=body.end_lineno,
                        name=name,
                        url=None,
                        source="\n".join(lines[body.lineno - 1 : body.end_lineno]),
                    )
            elif isinstance(body, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"utils.{body.name}" if is_utils else body.name

                if name not in inner_nodes:
                    inner_nodes[name] = Node(
                        file=str(fp),
                        line=body.lineno,
                        end_line=body.end_lineno,
                        name=name,
                        url=None,
                        source="\n".join(lines[body.lineno - 1 : body.end_lineno]),
                    )

        path = "/".join(dirs)
        for node in inner_nodes.values():
            node.file = path

        nodes.update(inner_nodes)

    def index_directory(self, nodes: dict[str, Node], idx_path: pathlib.Path, parents: list[str], index_dir: str) -> None:
        parents = (parents and parents.copy()) or []
        target = idx_path.joinpath(*parents, index_dir)
        parents.append(index_dir)
        idx = os.listdir(target)

        for file in idx:
            if file in ("types", "_types", "types_", "typings", "typing"):
                continue

            new_path = target / file
            if new_path.exists() and new_path.is_dir():
                self.index_directory(nodes, idx_path, parents, file)
            elif file.endswith(".py"):
                self.index_file(nodes, new_path, [*parents, file], file in ("utils.py", "utilities.py"))

    def index_lib(self) -> None:
        self.index_directory(self.nodes, self.repo_path, [], self.index_folder)

        for node in self.nodes.values():
            node.url = f"{self.repo_url}/blob/{self.branch}/{node.file}#L{node.line}-L{node.end_line}"

        self.keys = list(self.nodes.keys())

        if not self.version and "__version__" in self.keys:
            version = VERSION_REGEX.search(self.nodes["__version__"].source)
            if version:
                self.version = version.group(1)
            else:
                LOGGER.error(
                    "Unable to ascertain version: %r (%r)", self.nodes["__version__"], self.nodes["__version__"].source
                )

    def find_matches(self, word: str) -> list[Node]:
        return [self.nodes[v] for v in difflib.get_close_matches(word, self.keys, cutoff=0.55)]


class Indexes:
    __indexable: ClassVar[dict[str, Index]] = {
        "discord.py": Index("repos/discord.py", index_folder="discord", repo_url="https://github.com/Rapptz/discord.py"),
        "wavelink": Index("repos/wavelink", index_folder="wavelink", repo_url="https://github.com/PythonistaGuild/Wavelink"),
        "aiohttp": Index("repos/aiohttp", index_folder="aiohttp", repo_url="https://github.com/aio-libs/aiohttp"),
        "hondana": Index("repos/hondana", index_folder="hondana", repo_url="https://github.com/AbstractUmbra/Hondana"),
        "jishaku": Index("repos/jishaku", index_folder="jishaku", repo_url="https://github.com/Gorialis/Jishaku"),
    }

    def __init__(self) -> None:
        self.index: dict[str, Index] = {}
        self._is_indexed: bool = False
        self._do_index()

    @property
    def indexed(self) -> bool:
        return self._is_indexed

    @property
    def libraries(self) -> dict[str, str | None]:
        return {lib: index.version for lib, index in self.__indexable.items()}

    def get_query(self, lib: str, query: str) -> dict[str, Any] | None:
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
