"""The provided editors."""

import difflib
import io
import os
import subprocess  # nosec
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
    TypedDict,
    ValuesView,
    cast,
)

import ruamel.yaml.scalarstring
import tomlkit
from configupdater import ConfigUpdater

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
        assert isinstance(pre_commit_config, EditYAML)
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

        self.yaml = ruamel.yaml.YAML()
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


class PreCommitHook(TypedDict):
    """Pre-commit hook."""

    id: str
    alias: str
    name: str
    language_version: str
    files: str
    exclude: str
    types: List[str]
    types_or: List[str]
    exclude_types: List[str]
    args: List[str]
    stages: List[str]
    additional_dependencies: List[str]
    allways_run: bool
    verbose: bool
    log_file: str


class _PreCommitRepo(TypedDict):
    """Pre-commit repo."""

    repo: str
    rev: str
    hooks: List[PreCommitHook]


class _RepoHook(TypedDict):
    """Repo hook."""

    repo: _PreCommitRepo
    hooks: Dict[str, PreCommitHook]


class EditPreCommitConfig(EditYAML):
    """Edit the pre-commit config file."""

    def __init__(self, filename: str = ".pre-commit-config.yaml", fix_files: bool = True, **kwargs: Any):
        super().__init__(filename, **kwargs)

        self.repos_hooks: Dict[str, _RepoHook] = {}
        for repo in self["repos"]:
            self.repos_hooks.setdefault(
                repo["repo"], {"repo": repo, "hooks": {hook["id"]: hook for hook in repo["hooks"]}}
            )
        for repo in self["repos"]:
            for hook in repo["hooks"]:
                for tag in ("files", "excludes"):
                    if tag in hook and hook[tag].strip().startswith("(?x)"):
                        hook[tag] = ruamel.yaml.scalarstring.LiteralScalarString(hook[tag].strip())

        if fix_files:
            self.fix_files()

    def add_repo(self, repo: str, rev: Optional[str] = None) -> None:
        """Add a repo to the pre-commit config."""

        if rev is None:
            rev = run(
                ["gh", "release", "view", f"--repo={repo}", "--json=name", "--template={{.name}}"],
                stdout=subprocess.PIPE,
            ).stdout.strip()

        if repo not in self.repos_hooks:
            repo_obj: _PreCommitRepo = {"repo": repo, "rev": rev, "hooks": []}
            self["repos"].append(repo_obj)

            self.repos_hooks.setdefault(repo, {"repo": repo_obj, "hooks": {}})

    def add_hook(self, repo: str, hook: PreCommitHook, ci_skip: bool = False) -> None:
        """Add a hook to the pre-commit config."""

        if hook["id"] not in self.repos_hooks[repo]["hooks"]:
            self.repos_hooks[repo]["repo"]["hooks"].append(hook)
            self.repos_hooks[repo]["hooks"][hook["id"]] = hook

            if ci_skip:
                skip = self.setdefault("ci", {}).setdefault("skip", [])
                self.setdefault("ci", {})["skip"] = [*skip, hook["id"]]

    def create_files_regex(self, files: List[str], add_start_end: bool = True) -> str:
        """Create a regex to match the files."""
        files_joined = "\n  |".join(files)
        start = "^" if add_start_end else ""
        end = "$" if add_start_end else ""
        result = ruamel.yaml.scalarstring.LiteralScalarString(
            f"""(?x){start}(
  {files_joined}
){end}"""
        )

        return result

    def fix_files(self) -> None:
        """Fix the files regex."""

        for repo in self.data["repos"]:
            for hook in repo["hooks"]:
                for attribute in ("files", "exclude"):
                    if len(hook.get(attribute, "")) > 60:
                        attribute_value = hook[attribute]

                        add_start_end = False
                        if attribute_value.strip().startswith("(?x)"):
                            attribute_value = attribute_value.strip()[4:]
                        if attribute_value.strip().startswith("(") and attribute_value.strip().endswith(")"):
                            files_list = attribute_value.strip()[1:-1].split("|")
                        elif attribute_value.strip().startswith("(") and attribute_value.strip().endswith(
                            ")"
                        ):
                            files_list = attribute_value.strip()[1:-1].split("|")
                        elif attribute_value.strip().startswith("^(") and attribute_value.strip().endswith(
                            ")$"
                        ):
                            files_list = attribute_value.strip()[2:-2].split("|")
                            add_start_end = True
                        else:
                            continue

                        hook[attribute] = self.create_files_regex(
                            [f.strip() for f in files_list], add_start_end=add_start_end
                        )


class EditRenovateConfig(Edit):
    """
    Edit the Renovate config file.

    Conserve the comments, consider that we have at least the
    packageRules, and just before the regexManagers.
    """

    def __init__(self, filename: str = ".github/renovate.json5", **kwargs: Any):
        super().__init__(filename, **kwargs)

    def add(self, data: str, test: str) -> None:
        """Add an other setting to the renovate config."""

        if test in self.data:
            return

        if "regexManagers" in self.data:
            index = self.data.rindex("regexManagers")
            self.data = self.data[:index] + f"{data.strip()}," + self.data[index:]

        elif "packageRules" in self.data:
            index = self.data.rindex("packageRules")
            self.data = self.data[:index] + f"{data}," + self.data[index:]

    def add_regex_manager(self, data: str, test: str) -> None:
        """Add a regex manager to the renovate config."""

        if test in self.data:
            return

        if "regexManagers" in self.data:
            if "packageRules" in self.data:
                index = self.data.rindex("packageRules")
                index = self.data.rindex("]", 0, index)
                self.data = self.data[:index] + f"{data.strip()}," + self.data[index:]
            else:
                index = self.data.rindex("]")
                self.data = self.data[:index] + f"{data.strip()}," + self.data[index:]
        elif "packageRules" in self.data:
            index = self.data.rindex("packageRules")
            self.data = self.data[:index] + f"regexManagers: [{data.strip()},]," + self.data[index:]
        else:
            index = self.data.rindex("}")
            self.data = self.data[:index] + f"regexManagers: [{data.strip()},]," + self.data[index:]

    def add_package_rule(self, data: str, test: str) -> None:
        """Add a package rule to the renovate config."""

        if test in self.data:
            return

        if "packageRules" in self.data:
            index = self.data.rindex("]")
            self.data = self.data[:index] + f"{data.strip()}," + self.data[index:]
        else:
            index = self.data.rindex("}")
            self.data = self.data[:index] + f"packageRules: [{data.strip()},]," + self.data[index:]
