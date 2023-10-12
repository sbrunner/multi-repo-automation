"""The provided editors."""

import difflib
import io
import os
import subprocess  # nosec
import sys
import traceback
from abc import abstractmethod
from collections.abc import ItemsView, Iterator, KeysView, ValuesView
from types import TracebackType
from typing import Any, Literal, Optional, TypedDict, Union, cast

import json5
import ruamel.yaml.comments
import ruamel.yaml.scalarstring
import tomlkit
from configupdater import ConfigUpdater
from typing_extensions import Required

from multi_repo_automation.tools import edit, run


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
        exc_type: Optional[type[BaseException]],
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

            new_data = self.dump(self.data) if self.data else ""
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
                        try:
                            proc = run(
                                ["pre-commit", "run", "--color=never", "--files", self.filename], False
                            )
                            if proc.returncode != 0 and os.environ.get("DEBUG", "false").lower() in (
                                "true",
                                "1",
                            ):
                                proc = run(["pre-commit", "run", "--files", self.filename], False)
                                if proc.returncode != 0:
                                    edit([self.filename])
                        except subprocess.TimeoutExpired as exc:
                            print(exc)
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
    data: dict[str, Any]

    @abstractmethod
    def load(self, content: io.TextIOWrapper) -> dict[str, Any]:
        """Load the content."""
        del content
        raise NotImplementedError()

    @abstractmethod
    def dump(self, data: dict[str, Any]) -> str:
        """Load the content."""
        del data
        raise NotImplementedError()

    def get_empty(self) -> dict[str, Any]:
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

    def popitem(self) -> tuple[str, Any]:
        """Pop an item."""
        return self.data.popitem()

    def update(self, other: dict[str, Any]) -> None:
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
        self.yaml.width = width
        self.yaml.preserve_quotes = preserve_quotes
        self.yaml.indent(mapping=mapping, sequence=sequence, offset=offset)

        super().__init__(filename, **kwargs)

    def load(self, content: io.TextIOWrapper) -> dict[str, Any]:
        """Load the file."""
        return cast(dict[str, Any], self.yaml.load(content))

    def dump(self, data: dict[str, Any]) -> str:
        """Load the file."""
        out = io.StringIO()
        self.yaml.dump(self.data, out)
        return out.getvalue()

    def add_pre_commit_hook(self) -> None:
        with EditPreCommitConfig() as pre_commit_config:
            assert isinstance(pre_commit_config, EditPreCommitConfig)
            pre_commit_config.add_repo("https://github.com/pre-commit/mirrors-prettier", "v2.7.1")
            pre_commit_config.add_hook(
                "https://github.com/pre-commit/mirrors-prettier",
                {
                    "id": "prettier",
                    "additional_dependencies": pre_commit_config.commented_additional_dependencies(
                        ["prettier@2.8.4"], "npm"
                    ),
                },
            )


class EditTOML(_EditDict):
    """
    Edit a TOML file by keeping the comments, in a with instruction.

    ```python
    with EditTOML("file.toml") as toml:
        toml["key"] = "value"
    ```
    """

    def load(self, content: io.TextIOWrapper) -> dict[str, Any]:
        """Load the file."""
        return tomlkit.parse(content.read())

    def dump(self, data: dict[str, Any]) -> str:
        """Load the file."""
        return tomlkit.dumps(data)

    def add_pre_commit_hook(self) -> None:
        with EditPreCommitConfig() as pre_commit_config:
            assert isinstance(pre_commit_config, EditPreCommitConfig)
            pre_commit_config.add_repo("https://github.com/pre-commit/mirrors-prettier", "v2.7.1")
            pre_commit_config.add_hook(
                "https://github.com/pre-commit/mirrors-prettier",
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


class PreCommitHook(TypedDict, total=False):
    """Pre-commit hook."""

    id: Required[str]
    alias: str
    name: str
    language_version: str
    files: str
    exclude: str
    types: list[str]
    types_or: list[str]
    exclude_types: list[str]
    args: list[str]
    stages: list[str]
    additional_dependencies: list[str]
    always_run: bool
    verbose: bool
    log_file: str


class _PreCommitRepo(TypedDict):
    """Pre-commit repo."""

    repo: str
    rev: str
    hooks: list[PreCommitHook]


class _RepoHook(TypedDict):
    """Repo hook."""

    repo: _PreCommitRepo
    hooks: dict[str, PreCommitHook]


class EditPreCommitConfig(EditYAML):
    """Edit the pre-commit config file."""

    def __init__(
        self,
        filename: str = ".pre-commit-config.yaml",
        fix_files: bool = True,
        save_on_fixed_files: bool = False,
        **kwargs: Any,
    ):
        super().__init__(filename, **kwargs)

        self.repos_hooks: dict[str, _RepoHook] = {}
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

        if not save_on_fixed_files:
            self.original_data = self.dump(self.data)

    def add_pre_commit_hook(self) -> None:
        pass

    def add_repo(self, repo: str, rev: Optional[str] = None) -> None:
        """Add a repo to the pre-commit config."""

        if rev is None:
            rev = run(
                ["gh", "release", "view", f"--repo={repo}", "--json=tagName", "--template={{.tagName}}"],
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
                self.skip_ci(hook["id"])

    def commented_additional_dependencies(self, dependencies: list[str], type_: str) -> list[str]:
        """
        Add comments to the additional dependencies.

        The result will be like this:
        ```yaml
        - poetry==1.4.1 # pypi
        ```
        The `# pypi` is used by Renovate to know the type of the package.
        """
        result = ruamel.yaml.comments.CommentedSeq(dependencies)
        for index, _ in enumerate(dependencies):
            result.yaml_add_eol_comment(type_, index)
        return result

    def add_commented_additional_dependencies(
        self, hook: PreCommitHook, dependencies: list[str], type_: str
    ) -> None:
        """
        Add comments to the additional dependencies.

        The result will be like this:
        ```yaml
        - poetry==1.4.1 # pypi
        ```
        The `# pypi` is used by Renovate to know the type of the package.
        """
        if "additional_dependencies" not in hook:
            hook["additional_dependencies"] = ruamel.yaml.comments.CommentedSeq([])
        for dependency in dependencies:
            hook["additional_dependencies"].append(dependency)
        for index in range(len(hook["additional_dependencies"])):
            hook["additional_dependencies"].yaml_add_eol_comment(type_, index)  # type: ignore[attr-defined]

    def create_files_regex(self, files: list[str], add_start_end: bool = True) -> str:
        """Create a regex to match the files."""
        if len(files) == 1:
            return f"^{files[0]}$" if add_start_end else files[0]
        files_joined = "\n  |".join(files)
        start = "^" if add_start_end else ""
        end = "$" if add_start_end else ""
        result = ruamel.yaml.scalarstring.LiteralScalarString(
            f"""(?x){start}(
  {files_joined}
){end}"""
        )

        return result

    def skip_ci(self, hook_id: str) -> None:
        """Add hook in the list that will be ignore by pre-commit.ci."""

        no_skip = "skip" not in self.setdefault("ci", {})
        if hook_id not in self.setdefault("ci", {}).setdefault("skip", []):
            if hasattr(self["ci"]["skip"], "ca"):
                yaml_hooks = ruamel.yaml.comments.CommentedSeq([*self["ci"]["skip"], hook_id])
                yaml_hooks._yaml_comment = self["ci"][  # type: ignore # pylint: disable=protected-access
                    "skip"
                ].ca
                self["ci"]["skip"] = yaml_hooks
            else:
                self["ci"]["skip"].append(hook_id)

            if no_skip:
                self["ci"] = dict(self["ci"])

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

    def dump(self, data: dict[str, Any]) -> str:
        """Load the file."""

        new_data = []
        for key in ["ci"]:
            if key in data:
                new_data.append((key, data[key]))

        new_data += [e for e in data.items() if e[0] not in ("ci", "repos")]

        data = ruamel.yaml.comments.CommentedMap(new_data)

        for key in ["ci"]:
            data.ca.items[key] = [
                None,
                None,
                ruamel.yaml.CommentToken("\n\n", ruamel.yaml.error.CommentMark(0), None),
                None,
            ]

        return super().dump(data)


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

        if test not in data:
            raise ValueError(f"Test '{test}' not found in data '{data}'.")

        if test in self.data:
            return

        data = data.strip()
        data = data.rstrip(",")
        data = data.rstrip()
        data = f"{data},"

        if "regexManagers" in self.data:
            index = self.data.rindex("regexManagers")
            self.data = self.data[:index] + data + self.data[index:]
        elif "packageRules" in self.data:
            index = self.data.rindex("packageRules")
            self.data = self.data[:index] + data + self.data[index:]
        else:
            index = self.data.rindex("}")
            self.data = self.data[:index] + data + self.data[index:]

    def _clean_data(self, data: Union[str, list[Any], dict[str, Any]]) -> str:
        if isinstance(data, dict):
            data = json5.dumps(data, indent=2)
        if isinstance(data, list):
            data = json5.dumps(data, indent=2)
            data = data.strip()
            data = data.lstrip("[")
            data = data.rstrip("]")

        data = data.strip()
        data = data.lstrip("{")
        data = data.lstrip()
        data = data.rstrip(",")
        data = data.rstrip()
        data = data.rstrip("}")
        data = data.rstrip()
        return f" {{ {data} }},\n"

    def add_regex_manager(self, data: Union[str, list[Any], dict[str, Any]], test: str) -> None:
        """Add a regex manager to the Renovate config."""

        data = self._clean_data(data)

        if test not in data:
            raise ValueError(f"Test '{test}' not found in data '{data}'.")

        if test in self.data:
            return

        if "regexManagers" in self.data:
            if "packageRules" in self.data:
                index = self.data.rindex("packageRules")
                index = self.data.rindex("]", 0, index)
                self.data = self.data[:index] + data + self.data[index:]
            else:
                index = self.data.rindex("]")
                self.data = self.data[:index] + data + self.data[index:]
        elif "packageRules" in self.data:
            index = self.data.rindex("packageRules")
            self.data = self.data[:index] + f" regexManagers: [{data}],\n" + self.data[index:]
        else:
            index = self.data.rindex("}")
            self.data = self.data[:index] + f" regexManagers: [{data}],\n" + self.data[index:]

    def add_package_rule(self, data: Union[str, list[Any], dict[str, Any]], test: str) -> None:
        """Add a package rule to the Renovate config."""

        data = self._clean_data(data)

        if test not in data:
            raise ValueError(f"Test '{test}' not found in data '{data}'.")

        if test in self.data:
            return

        if "packageRules" in self.data:
            index = self.data.rindex("]")
            self.data = self.data[:index] + data + self.data[index:]
        else:
            index = self.data.rindex("}")
            self.data = self.data[:index] + f" packageRules: [{data}],\n" + self.data[index:]
