"""Some utility functions."""

import json
import os
import shlex
import subprocess  # nosec
import sys
from typing import Any, TypedDict, Union, cast

import yaml
from typing_extensions import Required


class HookDefinition(TypedDict, total=False):
    """Hook standard definition."""

    id: str
    args: list[str]
    files: str
    language_version: str
    additional_dependencies: list[str]


class RepoDefinition(TypedDict):
    """Repo standard definition."""

    repo: str
    rev: str
    hooks: list[HookDefinition]


class RepoRepresentation(TypedDict):
    """Repo representation used internally."""

    repo: RepoDefinition
    hooks: dict[str, HookDefinition]


_BROWSER = "xdg-open"


def get_browser() -> str:
    """Get the used browser."""
    return _BROWSER


def set_browser(browser: str) -> None:
    """Set the used browser."""
    global _BROWSER  # pylint: disable=global-statement
    _BROWSER = browser


_EDITOR = "xdg-open"


def get_editor() -> str:
    """Get the used editor."""
    return _EDITOR


def set_editor(editor: str) -> None:
    """Set the used editor."""
    global _EDITOR  # pylint: disable=global-statement
    _EDITOR = editor


class Repo(TypedDict, total=False):
    """The repository description."""

    dir: Required[str]
    name: Required[str]
    master_branch: str
    remote: str
    stabilization_branches: list[str]
    folders_to_clean: list[str]
    clean: bool


_REPO_CONFIG: Union[Repo, dict[str, None]] = {}


def set_repo_config(repo_config: Repo) -> None:
    """Set the repository configuration."""
    global _REPO_CONFIG  # pylint: disable=global-statement
    _REPO_CONFIG = repo_config


def get_repo_config() -> Repo:
    """Get the repository configuration."""
    repo = cast(Repo, _REPO_CONFIG)

    if not repo:
        if os.path.isfile(".repo.yaml"):
            with open(".repo.yaml", encoding="utf-8") as file:
                repo = cast(Repo, yaml.safe_load(file))

        if "remote" not in repo:
            remotes = run(["git", "remote", "--verbose"], stdout=subprocess.PIPE).stdout.strip().split("\n")
            for remote in remotes:
                if remote.startswith("upstream\t"):
                    repo["remote"] = "upstream"
                    break

            if "remote" not in repo:
                for remote in remotes:
                    if remote.startswith("origin\t"):
                        repo["remote"] = "origin"
                        break

            if "remote" not in repo:
                for remote in remotes:
                    repo["remote"] = remote.split("\t")[0]
                    break

        if "name" not in repo:
            remotes = run(["git", "remote", "--verbose"], stdout=subprocess.PIPE).stdout.strip().split("\n")
            for remote in remotes:
                if remote.startswith(f"{repo['remote']}\t"):
                    repo["name"] = remote.split()[1].split(":")[1].replace(".git", "")
                    break

        if "dir" not in repo:
            repo["dir"] = os.getcwd()

    return repo


def run(
    cmd: list[str], exit_on_error: bool = True, auto_fix_owner: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """Run a command."""
    print(f"$ {shlex.join(cmd)}")
    sys.stdout.flush()
    if "stdout" in kwargs and kwargs["stdout"] == subprocess.PIPE and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    timeout = os.environ.get("MRA_TIMEOUT")
    if timeout:
        kwargs.setdefault("timeout", int(timeout))
    process = subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check # nosec

    if auto_fix_owner and process.returncode != 0:
        run(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", "."], timeout=None)
        process = subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check # nosec

    if process.returncode != 0:
        print(f"Error on running: {shlex.join(cmd)}")
        if exit_on_error:
            sys.exit(process.returncode)
    return process


def edit(files: list[str]) -> None:
    """Edit the files in an editor."""
    for file in files:
        print(os.path.abspath(file))
        with open(file, "a", encoding="utf-8"):
            pass
        run([get_editor(), file])
        print("Press enter to continue")
        input()
        # Remove the file if he is empty
        if os.path.exists(file) and os.stat(file).st_size == 0:
            os.remove(file)


def gh(command: str, *args: str, **kwargs: Any) -> str:  # pylint: disable=invalid-name
    """Run a GitHub command."""
    return run(
        ["gh", command, f"--repo={get_repo_config()['name']}", *args], stdout=subprocess.PIPE, **kwargs
    ).stdout.strip()


def gh_json(command: str, fields: list[str], *args: str, **kwargs: Any) -> list[dict[str, str]]:
    """Get the JSON from a GitHub command."""
    return cast(list[dict[str, str]], json.loads(gh(command, f"--json={','.join(fields)}", *args, **kwargs)))
