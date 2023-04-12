"""Some utility functions."""

import os
import shlex
import subprocess  # nosec
import sys
from typing import Any, Dict, List, TypedDict


class HookDefinition(TypedDict, total=False):
    """Hook standard definition."""

    id: str
    args: List[str]
    files: str
    language_version: str
    additional_dependencies: List[str]


class RepoDefinition(TypedDict):
    """Repo standard definition."""

    repo: str
    rev: str
    hooks: List[HookDefinition]


class RepoRepresentation(TypedDict):
    """Repo representation used internally."""

    repo: RepoDefinition
    hooks: Dict[str, HookDefinition]


def run(
    cmd: List[str], exit_on_error: bool = True, auto_fix_owner: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """Run a command."""
    print(f"$ {shlex.join(cmd)}")
    sys.stdout.flush()
    if "stdout" in kwargs and kwargs["stdout"] == subprocess.PIPE and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    process = subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check # nosec

    if auto_fix_owner and process.returncode != 0:
        run(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", "."])
        process = subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check # nosec

    if process.returncode != 0:
        print(f"Error on running: {shlex.join(cmd)}")
        if exit_on_error:
            sys.exit(process.returncode)
    return process
