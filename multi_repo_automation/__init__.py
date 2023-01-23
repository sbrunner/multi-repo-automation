import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, TypedDict

import requests
import ruamel
import yaml
from identify import identify
from ruamel.yaml import YAML


def all_filenames(repo):
    return (
        run(["git", "ls-files"], cwd=repo["dir"], check=True, stdout=subprocess.PIPE, encoding="utf-8")
        .stdout.strip()
        .split("\n")
    )


def identify_all(repo):
    result = set()
    for filename in all_filenames(repo):
        result |= identify.tags_from_path(filename)
    return result


def identify(repo, type_):
    for filename in all_filenames(repo):
        if type_ in identify.tags_from_path(filename):
            return True
    return False


def run(cmd: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
    print(shlex.join(cmd))
    sys.stdout.flush()
    if "check" not in kwargs:
        kwargs["check"] = True
    return subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check


class Repo(TypedDict, total=False):
    """The repository description."""

    dir: str
    name: str
    types: List[str]
    master_branch: Optional[str]
    stabilization_branches: Optional[List[str]]
    folders_to_clean: Optional[List[str]]
    clean: bool


class Cwd:
    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self.cwd = os.getcwd()

    def __enter__(self) -> None:
        os.chdir(self.repo["dir"])

    def __exit__(self, *_: Any) -> None:
        os.chdir(self.cwd)


class CreateBranch:
    def __init__(
        self,
        repo: Repo,
        new_branch_name: str,
        commit_message: Optional[str] = None,
        force: bool = True,
        base_branch: Optional[str] = None,
        pr_body: Optional[str] = None,
    ) -> None:
        self.repo = repo
        if base_branch is None:
            base_branch = repo.get("master_branch", "master")
        self.base_branch = base_branch
        self.new_branch_name = new_branch_name
        self.commit_message = commit_message
        self.pr_body = pr_body
        self.force = force
        self.has_stashed = False
        self.pull_request_created = False
        self.old_branch_name = (
            run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def __enter__(self, *_: Any) -> None:
        run(
            [
                "docker",
                "run",
                "--rm",
                f"--volume={os.getcwd()}:/src",
                "sbrunner/vim",
                "chown",
                f"{run(['id', '-u'], check=True, stdout=subprocess.PIPE).stdout.decode().strip()}:"
                f"{run(['id', '-g'], check=True, stdout=subprocess.PIPE).stdout.decode().strip()}",
                "-R",
                ".",
            ],
            check=True,
        )
        for folder in self.repo.get("folders_to_clean", []):
            shutil.rmtree(folder, ignore_errors=True)
        if self.repo.get("clean", True):
            run(["git", "clean", "-dfX"])
            proc = run(
                ["git", "stash", "--all"], stdout=subprocess.PIPE, encoding="utf-8", env={}, check=True
            )
            self.has_stashed = proc.stdout.strip() != "No local changes to save"
        else:
            proc = run(["git", "stash"], stdout=subprocess.PIPE, encoding="utf-8", env={}, check=True)
            self.has_stashed = proc.stdout.strip() != "No local changes to save"
        run(["git", "fetch"], check=True)
        run(["git", "reset", "--hard", f"origin/{self.base_branch}"], check=True)
        if self.new_branch_name == self.old_branch_name:
            run(["git", "reset", "--hard", "origin", self.new_branch_name])
        else:
            run(["git", "branch", "--delete", "--force", self.new_branch_name])
            run(
                [
                    "git",
                    "checkout",
                    "-b",
                    self.new_branch_name,
                    f"origin/{self.base_branch}",
                ],
                check=True,
            )
        run(["git", "status"])

    def __exit__(self, exc_type, exc_val, exc_tb):
        del exc_val, exc_tb

        if self.commit_message and exc_type is None:
            self.pull_request_created, self.message = create_pull_request(
                self.repo,
                self.commit_message,
                force=self.force,
                base_branch=self.base_branch,
                body=self.pr_body,
            )
        if self.new_branch_name != self.old_branch_name:
            run(
                ["git", "checkout", self.old_branch_name],
                check=True,
            )
        if self.has_stashed:
            if run(["git", "stash", "pop"]).returncode != 0:
                run(["git", "reset", "--hard"], check=True)


def create_pull_request(
    repo: Repo,
    title: Optional[str] = None,
    commit: bool = True,
    label: str = "chore",
    body: Optional[str] = None,
    force: bool = True,
    base_branch: Optional[str] = None,
) -> Tuple[bool, str]:
    run(["git", "status", "--short"], check=True)
    if not run(["git", "status", "--short"], check=True, stdout=subprocess.PIPE).stdout.strip():
        return False, ""
    if base_branch is None:
        base_branch = repo.get("master_branch", "master")
    cmd = [
        "gh",
        "pr",
        "create",
        "--fill",
        f"--label={label}",
        f"--base={base_branch}",
    ]
    if commit:
        run(["git", "add", "--all"], check=True)
        assert title is not None
        with tempfile.NamedTemporaryFile() as message_file:
            message_file.write(f"{title}\n".encode())
            if body is not None:
                message_file.write(f"\n{body}\n".encode())
            message_file.flush()
            if run(["git", "commit", f"--file={message_file.name}"]).returncode != 0:
                run(["git", "add", "--all"], check=True)
                run(["git", "commit", "--no-verify", f"--file={message_file.name}"], check=True)

    if title is not None:
        cmd.extend(["--title", title])
        cmd.extend(["--body", body if body is not None else ""])
    else:
        cmd.append("--fill")

    if force:
        run(["git", "push", "--force"], check=True)
    else:
        run(["git", "push"], check=True)

    url = run(cmd, stdout=subprocess.PIPE).stdout.decode().strip()
    if not url:
        url = f"https://github.com/{repo['name']}/pulls"
    elif re.match(r"https://github.com/camptocamp/tilecloud/pull/[0-9]+", url):
        url = f"{url}/tiles"
    run(["/home/sbrunner/bin/firefox/firefox", url])
    return True, url


class Branch:
    def __init__(self, repo: Repo, branch_name: str, force: bool = False, push=True) -> None:
        self.repo = repo
        self.branch_name = branch_name
        self.force = force
        self.push = push
        self.has_stashed = False
        self.old_branch_name = (
            run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def __enter__(self, *_: Any) -> None:
        run(
            [
                "docker",
                "run",
                "--rm",
                f"--volume={os.getcwd()}:/src",
                "sbrunner/vim",
                "chown",
                f"{run(['id', '-u'], check=True, stdout=subprocess.PIPE).stdout.decode().strip()}:"
                f"{run(['id', '-g'], check=True, stdout=subprocess.PIPE).stdout.decode().strip()}",
                "-R",
                ".",
            ],
            check=True,
        )
        for folder in self.repo.get("folders_to_clean", []):
            shutil.rmtree(folder, ignore_errors=True)
        if self.repo.get("clean", True):
            run(["git", "clean", "-dfX"])
            self.has_stashed = run(["git", "stash", "--all"]).returncode == 0
        else:
            self.has_stashed = run(["git", "stash"]).returncode == 0

        if self.old_branch_name != self.branch_name:
            run(["git", "branch", "--delete", "--force", self.branch_name])
            run(
                ["git", "checkout", "-b", self.branch_name, "--track", f"origin/{self.branch_name}"],
                check=True,
            )
        else:
            run(["git", "pull", "--rebase"], check=True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        del exc_val, exc_tb

        if exc_type is None and self.push:
            if self.force:
                run(["git", "push", "--force"], check=True)
            else:
                run(["git", "push"], check=True)

        if self.branch_name != self.old_branch_name:
            run(["git", "checkout", self.old_branch_name])
        if self.has_stashed:
            if run(["git", "stash", "pop"]).returncode != 0:
                run(["git", "reset", "--hard"], check=True)


class Commit:
    def __init__(self, commit_message: str) -> None:
        self.commit_message = commit_message

    def __enter__(self, *_: Any) -> None:
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        del exc_val, exc_tb

        if exc_type is None:

            if not run(["git", "status", "--short"], check=True, stdout=subprocess.PIPE).stdout.strip():
                return
            run(["git", "add", "--all"], check=True)
            with tempfile.NamedTemporaryFile() as message_file:
                message_file.write(f"{self.commit_message}\n".encode())
                message_file.flush()
                if run(["git", "commit", f"--file={message_file.name}"]).returncode != 0:
                    run(["git", "add", "--all"], check=True)
                    run(["git", "commit", "--no-verify", f"--file={message_file.name}"], check=True)


class EditYAML:
    def __init__(self, filename: str):
        self.filename = filename
        self.data: Dict[str, Any] = {}
        self.yaml = YAML()
        self.yaml.default_flow_style = False
        self.yaml.width = 110

    def __enter__(self) -> "EditYAML":
        with open(self.filename, encoding="utf-8") as file:
            self.data = self.yaml.load(file)
        out = io.StringIO()
        self.yaml.dump(self.data, out)
        self.original_data = out.getvalue()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        del exc_val, exc_tb
        if exc_type is None:
            out = io.StringIO()
            self.yaml.dump(self.data, out)
            new_data = out.getvalue()
            if new_data != self.original_data:
                with open(self.filename, "w", encoding="utf-8") as f:
                    f.write(new_data)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        del self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        return self.data.setdefault(key, default)


def copy_file(from_: str, to_: str, only_if_already_exists: bool = True) -> None:
    if os.path.exists(to_):
        os.remove(to_)
        shutil.copyfile(from_, to_)
    elif not only_if_already_exists:
        shutil.copyfile(from_, to_)


def verify_type(repo: Repo) -> List[str]:
    with Branch(repo, repo.get("master_branch", "master"), push=False):
        files = run(["git", "ls-files", "Dockerfile", "*/Dockerfile"], stdout=subprocess.PIPE).stdout.strip()
        if files != b"":  # found
            if "docker" not in repo["types"]:
                print("missing docker")
                input()
        else:
            if "docker" in repo["types"]:
                print("extra docker")
                input()

        files = run(
            ["git", "ls-files", "poetry.lock", "*/poetry.lock"], stdout=subprocess.PIPE
        ).stdout.strip()
        if files != b"":  # found
            if "python" not in repo["types"]:
                print("missing python")
                input()
        else:
            if "python" in repo["types"]:
                print("extra python")
                input()

        files = run(["git", "ls-files", "Chart.yaml", "*/Chart.yaml"], stdout=subprocess.PIPE).stdout.strip()
        if files != b"":  # found
            if "helm" not in repo["types"]:
                print("missing helm")
                input()
        else:
            if "helm" in repo["types"]:
                print("extra helm")
                input()

        files = run(["git", "ls-files", "action.yml", "*/action.yml"], stdout=subprocess.PIPE).stdout.strip()
        if files != b"":  # found
            if "action" not in repo["types"]:
                print("missing action")
                input()
        else:
            if "action" in repo["types"]:
                print("extra action")
                input()

        files = run(
            ["git", "ls-files", "package.json", "*/package.json"], stdout=subprocess.PIPE
        ).stdout.strip()
        if files != b"":  # found
            if "javascript" not in repo["types"]:
                print("missing javascript")
                input()
        else:
            if "javascript" in repo["types"]:
                print("extra javascript")
                input()

        return []


def git_grep(text: str, args: List[str] = []) -> None:
    proc = run(["git", "grep", *args, "--", text], stdout=subprocess.PIPE, encoding="utf-8")
    files = set()
    for line in proc.stdout.split("\n"):
        if line and not line.startswith("Binary file "):
            print(f"{os.getcwd()}/{line}")
            files.add(line.split(":")[0])
    return files


def replace(file: str, search: str, replace: str) -> None:
    with open(file, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(search, replace, content)
    with open(file, "w", encoding="utf-8") as f:
        f.write(content)


def edit(repo: Repo, files: List[str]) -> None:
    for file in files:
        print(f"{repo['dir']}/{file}")
        run(["code", f"{repo['dir']}/{file}"], check=True)
        print("Press enter to continue")
        input()


def update_stabilization_branches(repo: Repo) -> List[str]:
    import c2cciutils.security

    security_response = requests.get(
        f"https://raw.githubusercontent.com/{repo['name']}/{repo.get('master_branch', 'master')}/SECURITY.md",
        headers=c2cciutils.add_authorization_header({}),
        timeout=int(os.environ.get("C2CCIUTILS_TIMEOUT", "30")),
    )
    if security_response.ok:
        security = c2cciutils.security.Security(security_response.text)

        version_index = security.headers.index("Version")
        support_index = security.headers.index("Supported Until")
        versions = set()
        for d in security.data:
            if d[support_index] != "Unsupported" and d[version_index] != repo.get("master_branch", "master"):
                versions.add(d[version_index])
        if versions:
            repo["stabilization_branches"] = list(versions)

    for b in repo.get("stabilization_branches", []):
        with Branch(repo, b, push=False):
            pass


def do_on_base_branches(repo: Repo, branch_prefix: str, func: Callable[[Repo], None]) -> List[str]:
    result = set()
    branches = [*repo.get("stabilization_branches", []), repo.get("master_branch", "master")]
    for branch in branches:

        create_branch = CreateBranch(
            repo,
            f"{self.branch_prefix}-{branch}",
            "Fix pull requests check workflow, use our CI token",
            base_branch=branch,
        )
        with create_branch:
            func(repo)
        if create_branch.pull_request_created:
            if create_branch.message:
                result.add(create_branch.message)
            else:
                result.add(f"https://github.com/{repo['name']}/pulls")

    return list(result)
