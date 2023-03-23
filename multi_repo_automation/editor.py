"""The provided editors."""

import io
import os
import traceback
from abc import abstractmethod
from types import TracebackType
from typing import Any, Dict, Iterator, List, Literal, Optional, Type, cast

import tomlkit
from configupdater import ConfigUpdater
from ruamel.yaml import YAML

from multi_repo_automation.tools import (
    HookDefinition,
    RepoDefinition,
    RepoRepresentation,
    run,
)


def add_pre_commit_hook(repo: str, rev: str, hook: HookDefinition) -> None:
    """
    Add the pre-commit hook.

    To check that the configuration is correct.

    Example:
    -------
    ```python
    mra.add_pre_commit_hook(
        "https://github.com/pre-commit/mirrors-prettier",
        "v2.7.1",
        {"id": "prettier", "additional_dependencies": ["prettier@2.8.4"]},
    )
    ```
    """
    with EditYAML(
        ".pre-commit-config.yaml", add_pre_commit_configuration_if_modified=False
    ) as pre_commit_config:
        repos_hooks: Dict[str, RepoRepresentation] = {}
        for repo_ in cast(List[RepoDefinition], pre_commit_config.setdefault("repos", [])):
            repos_hooks.setdefault(
                repo_["repo"], {"repo": repo_, "hooks": {hook["id"]: hook for hook in repo_["hooks"]}}
            )

        if repo not in repos_hooks:
            repo_obj: RepoDefinition = {"repo": repo, "rev": rev, "hooks": []}
            pre_commit_config["repos"].append(repo_obj)

            repos_hooks.setdefault(repo, {"repo": repo_obj, "hooks": {}})

        if hook["id"] not in repos_hooks[repo]["hooks"]:
            repos_hooks[repo]["repo"]["hooks"].append(hook)
            repos_hooks[repo]["hooks"][hook["id"]] = hook
        else:
            current_dependency_base = set()
            for dependency in repos_hooks[repo]["hooks"][hook["id"]].get("additional_dependencies", []):
                current_dependency_base.add(dependency.split("@")[0])
            for dependency in hook.get("additional_dependencies", []):
                dependency_base = dependency.split("@")[0]
                if dependency_base not in current_dependency_base:
                    repos_hooks[repo]["hooks"][hook["id"]].setdefault("additional_dependencies", []).append(
                        dependency
                    )


class Edit:
    r"""
    Edit a file.

    Usage:

    ```python
    with Edit("file.txt") as file:
        file.content = "Header\n" + file.content
    ```
    """

    def __init__(
        self,
        filename: str,
        pre_commit_repo: Optional[str] = None,
        pre_commit_rev: Optional[str] = None,
        pre_commit_hook: Optional[HookDefinition] = None,
    ) -> None:
        """Initialize."""
        self.filename = filename
        self.pre_commit_repo = pre_commit_repo
        self.pre_commit_rev = pre_commit_rev
        self.pre_commit_hook = pre_commit_hook
        self.exists = os.path.exists(filename)
        if not self.exists:
            with open(filename, "w", encoding="utf-8") as opened_file:
                pass
        with open(self.filename, encoding="utf-8") as opened_file:
            self.content = opened_file.read()
            self.original_content = self.content

    def __enter__(self) -> "Edit":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        del exc_tb

        if exc_type is not None:
            print("=" * 30)
            print(type(self).__name__)
            print(exc_type.__name__)
            print(exc_val)
            traceback.print_exc()

        if not self.exists and not self.content:
            os.remove(self.filename)
            return False

        if self.content != self.original_content:
            if (
                self.pre_commit_repo is not None
                and self.pre_commit_rev is not None
                and self.pre_commit_hook is not None
            ):
                add_pre_commit_hook(self.pre_commit_repo, self.pre_commit_rev, self.pre_commit_hook)
            with open(self.filename, "w", encoding="utf-8") as opened_file:
                opened_file.write(self.content)

            if os.path.exists(".pre-commit-config.yaml"):
                run(["pre-commit", "run", "--files", self.filename], False)
        return False


class _EditDict:
    data: Dict[str, Any]

    original_data: Optional[str]

    def __init__(
        self,
        filename: str,
        force: bool = False,
        add_pre_commit_configuration_if_modified: bool = True,
    ):
        """Initialize the object."""
        self.filename = filename
        self.data: Dict[str, Any] = {}
        self.force = force
        self.exists = os.path.exists(filename)
        self.add_pre_commit_configuration_if_modified = add_pre_commit_configuration_if_modified

    def __enter__(self) -> "_EditDict":
        """Load the file."""
        if self.exists:
            with open(self.filename, encoding="utf-8") as file:
                self.data = self.load(file)  # nosec
        self.original_data = self.dump(self.data)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Save the file if the data has changed."""
        del exc_tb

        if exc_type is not None:
            print("=" * 30)
            print(type(self).__name__)
            print(exc_type.__name__)
            print(exc_val)
            traceback.print_exc()

        if exc_type is None:
            if not self.exists and not self.data:
                os.remove(self.filename)
                return False

            new_data = self.dump(self.data)
            if self.force or new_data != self.original_data:
                if self.add_pre_commit_configuration_if_modified:
                    self.add_pre_commit_hook()

                with open(self.filename, "w", encoding="utf-8") as file_:
                    file_.write(new_data)
                if os.path.exists(".pre-commit-config.yaml"):
                    run(["pre-commit", "run", "--files", self.filename], False)
        return False

    @abstractmethod
    def load(self, content: io.TextIOWrapper) -> Dict[str, Any]:
        """Load the content."""
        del content
        raise NotImplementedError()

    @abstractmethod
    def dump(self, data: Dict[str, Any]) -> str:
        """Load the content."""
        del data
        raise NotImplementedError()

    def add_pre_commit_hook(self) -> None:
        """Add the pre-commit hook."""

    def __getitem__(self, key: str) -> Any:
        """Get the value for the key."""
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set the value for the key."""
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete the key."""
        del self.data[key]

    def __contains__(self, key: str) -> bool:
        """Check if the key is in the data."""
        return key in self.data

    def __iter__(self) -> Iterator[str]:
        """Iterate over the keys."""
        return iter(self.data)

    def __len__(self) -> int:
        """Return the number of keys."""
        return len(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        """Get the value for the key."""
        return self.data.get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        """Set the default value for the key."""
        return self.data.setdefault(key, default)


class EditYAML(_EditDict):
    """
    Edit a YAML file by keeping the comments, in a with instruction.

    ```python
    with EditYAML("file.yaml") as yaml:
        yaml["key"] = "value"
    ```
    """

    def __init__(
        self,
        filename: str,
        width: int = 110,
        default_flow_style: bool = False,
        preserve_quotes: bool = True,
        mapping: int = 2,
        sequence: int = 4,
        offset: int = 2,
        force: bool = False,
        add_pre_commit_configuration_if_modified: bool = True,
    ):
        """Initialize the object."""

        super().__init__(filename, force, add_pre_commit_configuration_if_modified)

        self.yaml = YAML()
        self.yaml.default_flow_style = default_flow_style
        self.yaml.width = width  # type: ignore
        self.yaml.preserve_quotes = preserve_quotes  # type: ignore
        self.yaml.indent(mapping=mapping, sequence=sequence, offset=offset)

    def load(self, content: io.TextIOWrapper) -> Dict[str, Any]:
        """Load the file."""
        return cast(Dict[str, Any], self.yaml.load(content))

    def dump(self, data: Dict[str, Any]) -> str:
        """Load the file."""
        out = io.StringIO()
        self.yaml.dump(self.data, out)
        return out.getvalue()

    def add_pre_commit_hook(self) -> None:
        add_pre_commit_hook(
            "https://github.com/pre-commit/mirrors-prettier",
            "v2.7.1",
            {"id": "prettier", "additional_dependencies": ["prettier@2.8.4"]},
        )


class EditTOML(_EditDict):
    """
    Edit a TOML file by keeping the comments, in a with instruction.

    ```python
    with EditTOML("file.toml") as toml:
        toml["key"] = "value"
    ```
    """

    def load(self, content: io.TextIOWrapper) -> Dict[str, Any]:
        """Load the file."""
        return tomlkit.parse(content.read())

    def dump(self, data: Dict[str, Any]) -> str:
        """Load the file."""
        return tomlkit.dumps(data)

    def add_pre_commit_hook(self) -> None:
        add_pre_commit_hook(
            "https://github.com/pre-commit/mirrors-prettier",
            "v2.7.1",
            {
                "id": "prettier",
                "additional_dependencies": [
                    "prettier@2.8.4",
                    "prettier-plugin-toml@0.3.1",
                ],
            },
        )


class EditConfig(_EditDict):
    """
    Edit a config file by keeping the comments, in a with instruction.

    ```python
    with EditConfig("file.ini") as config:
        config["key"] = "value"
    ```
    """

    def __init__(
        self,
        filename: str,
        force: bool = False,
        add_pre_commit_configuration_if_modified: bool = True,
    ):
        """Initialize the object."""

        super().__init__(filename, force, add_pre_commit_configuration_if_modified)

        self.updater = ConfigUpdater()

    def load(self, content: io.TextIOWrapper) -> Dict[str, Any]:
        """Load the file."""
        return cast(Dict[str, Any], self.updater.read_string(content.read()))

    def dump(self, data: Dict[str, Any]) -> str:
        """Load the file."""
        del data

        out = io.StringIO()
        self.updater.write(out)
        return out.getvalue()
