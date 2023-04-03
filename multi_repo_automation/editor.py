"""The provided editors."""

import difflib
import io
import os
import sys
import traceback
from abc import abstractmethod
from types import TracebackType
from typing import (
    Any,
    Dict,
    ItemsView,
    Iterator,
    KeysView,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    ValuesView,
    cast,
)

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
                if "@" in dependency:
                    current_dependency_base.add(dependency.split("@")[0])
                elif "==" in dependency:
                    current_dependency_base.add(dependency.split("==")[0])
                else:
                    current_dependency_base.add(dependency)
            for dependency in hook.get("additional_dependencies", []):
                dependency_base = dependency.split("@")[0]
                if dependency_base not in current_dependency_base:
                    repos_hooks[repo]["hooks"][hook["id"]].setdefault("additional_dependencies", []).append(
                        dependency
                    )


class _Edit:
    filename: str
    data: Any
    force: bool
    exists: bool
    add_pre_commit_configuration_if_modified: bool
    original_data: str
    run_pre_commit: bool

    def __init__(
        self,
        filename: str,
        force: bool = False,
        add_pre_commit_configuration_if_modified: bool = True,
        run_pre_commit: bool = True,
        diff: bool = False,
    ):
        """Initialize the object."""
        self.filename = filename
        self.force = force
        self.exists = os.path.exists(filename)
        self.add_pre_commit_configuration_if_modified = add_pre_commit_configuration_if_modified
        self.run_pre_commit = run_pre_commit
        self.diff = diff

        if self.exists:
            with open(self.filename, encoding="utf-8") as file:
                self.data = self.load(file)  # nosec
        else:
            self.data = self.get_empty()
        self.original_data = self.dump(self.data)

    def __enter__(self) -> "_Edit":
        """Load the file."""
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

                if self.diff:
                    sys.stdout.writelines(
                        difflib.unified_diff(
                            self.original_data.splitlines(keepends=True),
                            new_data.splitlines(keepends=True),
                        )
                    )
                else:
                    with open(self.filename, "w", encoding="utf-8") as file_:
                        file_.write(new_data)
                    if os.path.exists(".pre-commit-config.yaml") and self.run_pre_commit:
                        run(["pre-commit", "run", "--files", self.filename], False)
        return False

    @abstractmethod
    def load(self, content: io.TextIOWrapper) -> Any:
        """Load the content."""
        del content
        raise NotImplementedError()

    @abstractmethod
    def dump(self, data: Any) -> str:
        """Load the content."""
        del data
        raise NotImplementedError()

    @abstractmethod
    def get_empty(self) -> Any:
        """Get the empty data."""

    def add_pre_commit_hook(self) -> None:
        """Add the pre-commit hook."""


class Edit(_Edit):
    r"""
    Edit a text file.

    Usage:

    ```python
    with Edit("file.txt") as file:
        file.content = "Header\n" + file.content
    ```
    """

    def load(self, content: io.TextIOWrapper) -> Any:
        """Load the content."""
        return content.read()

    def dump(self, data: Any) -> str:
        """Load the content."""
        assert isinstance(data, str)
        return data

    def get_empty(self) -> Any:
        """Get the empty data."""
        return ""


class _EditDict(_Edit):
    data: Dict[str, Any]

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

    def get_empty(self) -> Dict[str, Any]:
        """Get the empty data."""
        return {}

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

    def keys(self) -> KeysView[str]:
        """Return the keys."""
        return self.data.keys()

    def values(self) -> ValuesView[Any]:
        """Return the values."""
        return self.data.values()

    def items(self) -> ItemsView[str, Any]:
        """Return the items."""
        return self.data.items()

    def pop(self, key: str, default: Any = None) -> Any:
        """Pop the key."""
        return self.data.pop(key, default)

    def popitem(self) -> Tuple[str, Any]:
        """Pop an item."""
        return self.data.popitem()

    def update(self, other: Dict[str, Any]) -> None:
        """Update the data."""
        self.data.update(other)


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
        **kwargs: Any,
    ):
        """Initialize the object."""

        self.yaml = YAML()
        self.yaml.default_flow_style = default_flow_style
        self.yaml.width = width  # type: ignore
        self.yaml.preserve_quotes = preserve_quotes  # type: ignore
        self.yaml.indent(mapping=mapping, sequence=sequence, offset=offset)

        super().__init__(filename, **kwargs)

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

    updater: ConfigUpdater

    def __init__(
        self,
        filename: str,
        **kwargs: Any,
    ):
        """Initialize the object."""

        self.updater = ConfigUpdater()
        super().__init__(filename, **kwargs)

    def load(self, content: io.TextIOWrapper) -> Any:
        """Load the file."""
        return self.updater.read_string(content.read())

    def dump(self, data: Any) -> str:
        """Load the file."""

        out = io.StringIO()
        data.write(out)
        return out.getvalue()

    def get_empty(self) -> Any:
        """Get the empty data."""
        return self.updater
