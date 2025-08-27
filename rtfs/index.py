from __future__ import annotations

import ast
import configparser
import logging
import os
import pathlib
import re
import subprocess  # noqa: S404 # accepted use

from yarl import URL

from .fuzzy import extract

LOGGER = logging.getLogger(__name__)
VERSION_REGEX = re.compile(r"__version__\s*=\s*(?:'|\")((?:\w|\.)*)(?:'|\")")

__all__ = ("Node",)


def _get_attr_name(attr: ast.Attribute) -> str | None:
    if type(attr.value) is ast.Attribute:
        return _get_attr_name(attr.value)

    return None


def _transform_path(path: str) -> str:
    # discord/ext/commands/bot.py -> discord.ext.commands.bot
    return path.replace("/", ".").removesuffix(".py")


def _has_overload(nodes: list[ast.expr]) -> bool:
    return any("overload" in node.id for node in nodes if isinstance(node, ast.Name))


class Node:
    url: str
    __slots__ = (
        "end_line",
        "file",
        "full_name",
        "line",
        "short_name",
        "source",
        "url",
    )

    def __init__(
        self,
        *,
        file: str | None,
        line: int,
        end_line: int | None,
        full_name: str | None = None,  # late init
        short_name: str,
        source: str,
    ) -> None:
        self.file = file
        self.line = line
        self.end_line = end_line
        self.full_name = full_name
        self.short_name = short_name
        self.source = source

    def __repr__(self) -> str:
        return (
            f"<Node file={self.file} "
            f"line={self.line} "
            f"end_line={self.end_line} "
            f"full_path={self.full_name} "
            f"name={self.short_name} "
            f"url={self.url}>"
        )


class Index:
    __slots__ = (
        "branch",
        "commit",
        "index_folder",
        "keys",
        "library",
        "nodes",
        "repo_path",
        "repo_url",
        "version",
    )

    def __init__(
        self,
        *,
        library: str,
        repo_path: str,
        index_folder: str,
        repo_url: str,
        branch: str | None = None,
        version: str | None = None,
    ) -> None:
        self.library: str = library
        self.repo_path: pathlib.Path = pathlib.Path() / repo_path

        if index_folder in ("", ".", "./"):
            self.index_folder = ""
        else:
            self.index_folder = index_folder

        self.repo_url: URL = URL(repo_url)
        self.version: str | None = version
        self.nodes: dict[str, Node] = {}
        self.keys: list[str] = []

        if not self.repo_path.exists():
            self._clone_repo(self.repo_url, self.repo_path, branch)

        self.branch = self._process_git_dir()
        self.commit = self._process_current_commit()

    def _clone_repo(self, url: URL, path: pathlib.Path, branch_name: str | None) -> None:
        path.mkdir(parents=True, exist_ok=True)

        proc = ["git", "clone", str(url), str(self.repo_path)]
        branch = ["-b", branch_name] if branch_name else []

        proc.extend(branch)

        subprocess.run(proc, check=True)  # noqa: S603 # trusted input

    def _process_git_dir(self) -> str:
        git_path = self.repo_path / ".git"
        if not git_path.exists():
            msg = f"{self.repo_path} does not appear to be a valid git directory."
            raise ValueError(msg)

        head_path = git_path / "HEAD"
        current_branch = head_path.read_text("utf-8").rsplit("/")[-1]

        if not current_branch:
            return self._process_git_config()

        return current_branch.strip()

    def _process_git_config(self) -> str:
        git_config_path = self.repo_path / ".git" / "config"
        if not git_config_path.exists():
            msg = f"{self.repo_path} does not appear to be a valid git directory."
            raise ValueError(msg)

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
                            short_name=name,
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
                            short_name=name,
                            source="\n".join(src[body_part.lineno - 1 : body_part.end_lineno]),
                        )
            elif isinstance(body_part, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not body_part.name.startswith("__"):
                    name = class_name + "." + body_part.name
                    nodes[name] = Node(
                        file=None,
                        line=body_part.lineno,
                        end_line=body_part.end_lineno,
                        short_name=name,
                        source="\n".join(src[body_part.lineno - 1 : body_part.end_lineno]),
                    )
                self.index_class_function(nodes, cls, src, body_part)

    def index_file(self, nodes: dict[str, Node], fp: pathlib.Path, dirs: list[str], *, is_utils: bool = False) -> None:
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
                    short_name=body.name,
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
                        short_name=name,
                        source="\n".join(lines[body.lineno - 1 : body.end_lineno]),
                    )
            elif isinstance(body, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_overload(body.decorator_list):
                    continue
                name = f"utils.{body.name}" if is_utils else body.name

                if name not in inner_nodes:
                    inner_nodes[name] = Node(
                        file=str(fp),
                        line=body.lineno,
                        end_line=body.end_lineno,
                        short_name=name,
                        source="\n".join(lines[body.lineno - 1 : body.end_lineno]),
                    )

        path = "/".join(dirs)
        for node in inner_nodes.values():
            node.file = path
            node.full_name = f"{_transform_path(path)}.{node.short_name}"

        inner_nodes = {node.full_name: node for node in inner_nodes.values()}  # pyright: ignore[reportAssignmentType] # we assert the attribute above
        nodes.update(inner_nodes)

    def index_directory(self, nodes: dict[str, Node], idx_path: pathlib.Path, parents: list[str], index_dir: str) -> None:
        parents = (parents and parents.copy()) or []
        target = idx_path.joinpath(*parents, index_dir)
        parents.append(index_dir)
        idx = os.listdir(target)  # noqa: PTH208 # this is okay so we don't need string manip everywhere

        for file in idx:
            if file in ("types", "_types", "types_", "typings", "typing"):
                continue

            new_path = target / file
            if new_path.exists() and new_path.is_dir():
                self.index_directory(nodes, idx_path, parents, file)
            elif file.endswith(".py"):
                self.index_file(nodes, new_path, [*parents, file], is_utils=file in ("utils.py", "utilities.py"))

    def _find_version(self) -> Node | None:
        for node, value in self.nodes.items():
            version = node.rsplit(".")[-1]
            if version == "__version__":
                return value
        LOGGER.error("Unable to resolve version for library %r", self.library)
        return None

    def index_lib(self) -> None:
        self.index_directory(self.nodes, self.repo_path, [], self.index_folder)

        for node in self.nodes.values():
            node.url = f"{self.repo_url}/blob/{self.branch}/{node.file}#L{node.line}-L{node.end_line}"

        self.keys = list(self.nodes.keys())
        version_dunder = self._find_version()
        LOGGER.debug("Version dunder for %r identified as %r.", self.library, version_dunder)

        if not self.version and version_dunder:
            LOGGER.debug("Version source is %r", version_dunder.source)
            search = VERSION_REGEX.search(version_dunder.source)
            if search:
                self.version = search.group(1)

    def find_matches(self, word: str) -> list[Node]:
        return [self.nodes[v[0]] for v in extract(word, self.keys, score_cutoff=20, limit=3)]
