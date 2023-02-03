"""Tools to automated changes on multiple repositories."""

import argparse
import io
import os
import re
import shlex
import shutil
import subprocess  # nosec
import sys
import tempfile
from types import TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    TypedDict,
)

import identify.identify as identify_
import requests
import yaml
from ruamel.yaml import YAML


class Repo(TypedDict, total=False):
    """The repository description."""

    dir: str
    name: str
    master_branch: str
    stabilization_branches: List[str]
    folders_to_clean: List[str]
    clean: bool


def all_filenames(repo: Repo) -> List[str]:
    """Get all the filenames of the repository."""
    return (
        run(["git", "ls-files"], cwd=repo["dir"], stdout=subprocess.PIPE, encoding="utf-8")
        .stdout.strip()
        .split("\n")
    )


def identify_all(repo: Repo) -> Set[str]:
    """Get all the types of the repository."""
    result: Set[str] = set()
    for filename in all_filenames(repo):
        result |= identify_.tags_from_path(filename)
    return result


def identify(repo: Repo, type_: str) -> bool:
    """Check if the repository contains a file of the given type."""
    for filename in all_filenames(repo):
        if type_ in identify_.tags_from_path(filename):
            return True
    return False


def run(cmd: List[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a command."""
    print(shlex.join(cmd))
    sys.stdout.flush()
    if "check" not in kwargs:
        kwargs["check"] = True
    if "stdout" in kwargs and kwargs["stdout"] == subprocess.PIPE and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    return subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check # nosec


class Cwd:
    """
    Change the cwd in a with instruction.

    ```python with Cwd(repo):     # Do something in the repo ```
    """

    def __init__(self, repo: Repo) -> None:
        """Initialize the context manager."""
        self.repo = repo
        self.cwd = os.getcwd()

    def __enter__(self) -> None:
        """Change the cwd."""
        os.chdir(self.repo["dir"])

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Restore the cwd."""
        os.chdir(self.cwd)
        return False


class CreateBranch:
    """
    Create a branch in a with instruction.

    ```python
    result_urls = []
    create_branch = mra.CreateBranch(
        repo,
        "branch",
        "Commit message",
    )
    with create_branch:
        # Do something

    if create_branch.pull_request_created:
        if create_branch.message:
            result_urls.append(create_branch.message)
        else:
            result_urls.append(f"https://github.com/{repo['name']}/pulls")
    ```
    """

    message: Optional[str]

    def __init__(
        self,
        repo: Repo,
        new_branch_name: str,
        commit_message: Optional[str] = None,
        force: bool = True,
        base_branch: Optional[str] = None,
        pr_body: Optional[str] = None,
    ) -> None:
        """Initialize."""
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
        self.old_branch_name = run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def __enter__(self, *_: Any) -> None:
        """Create the branch."""
        run(
            [
                "docker",
                "run",
                "--rm",
                f"--volume={os.getcwd()}:/src",
                "sbrunner/vim",
                "chown",
                f"{run(['id', '-u'], stdout=subprocess.PIPE).stdout.strip()}:"
                f"{run(['id', '-g'], stdout=subprocess.PIPE).stdout.strip()}",
                "-R",
                ".",
            ],
        )
        for folder in self.repo.get("folders_to_clean") or []:
            shutil.rmtree(folder, ignore_errors=True)
        if self.repo.get("clean", True):
            run(["git", "clean", "-dfX"])
            proc = run(["git", "stash", "--all"], stdout=subprocess.PIPE, encoding="utf-8", env={})
            self.has_stashed = proc.stdout.strip() != "No local changes to save"
        else:
            proc = run(["git", "stash"], stdout=subprocess.PIPE, encoding="utf-8", env={})
            self.has_stashed = proc.stdout.strip() != "No local changes to save"
        run(["git", "fetch"])
        run(["git", "reset", "--hard", f"origin/{self.base_branch}", "--"])
        run(["git", "checkout", self.repo.get("master_branch") or "master"])
        if self.new_branch_name == self.old_branch_name:
            run(["git", "reset", "--hard", f"origin/{self.new_branch_name}", "--"])
        else:
            run(["git", "branch", "--delete", "--force", self.new_branch_name], check=False)
            run(
                [
                    "git",
                    "checkout",
                    "-b",
                    self.new_branch_name,
                    f"origin/{self.base_branch}",
                ],
            )
        run(["git", "status"])

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Create the pull request."""
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
            run(["git", "checkout", self.old_branch_name, "--"])
        if self.has_stashed:
            if run(["git", "stash", "pop"], check=False).returncode != 0:
                run(["git", "reset", "--hard"])
        return False


def create_pull_request(
    repo: Repo,
    title: Optional[str] = None,
    commit: bool = True,
    label: str = "chore",
    body: Optional[str] = None,
    force: bool = True,
    base_branch: Optional[str] = None,
) -> Tuple[bool, str]:
    """Create a pull request."""
    run(["git", "status", "--short"])
    if not run(["git", "status", "--short"], stdout=subprocess.PIPE).stdout.strip():
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
        run(["git", "add", "--all"])
        assert title is not None  # nosec
        with tempfile.NamedTemporaryFile() as message_file:
            message_file.write(f"{title}\n".encode())
            if body is not None:
                message_file.write(f"\n{body}\n".encode())
            message_file.flush()
            if run(["git", "commit", f"--file={message_file.name}"], check=False).returncode != 0:
                run(["git", "add", "--all"])
                run(["git", "commit", "--no-verify", f"--file={message_file.name}"])

    if title is not None:
        cmd.extend(["--title", title])
        cmd.extend(["--body", body if body is not None else ""])
    else:
        cmd.append("--fill")

    if force:
        run(["git", "push", "--force"])
    else:
        run(["git", "push"])

    url_proc = run(cmd, stdout=subprocess.PIPE, check=False)
    url = url_proc.stdout.strip()
    if url_proc.returncode != 0 or not url:
        url = f"https://github.com/{repo['name']}/pulls"
    elif re.match(r"https://github.com/camptocamp/tilecloud/pull/[0-9]+", url):
        url = f"{url}/tiles"
    return True, url


class Branch:
    """
    Checkout a branch in a with instruction.

    ```python with Branch(repo, "my_branch"):     # Do something ```
    """

    def __init__(self, repo: Repo, branch_name: str, force: bool = False, push: bool = True) -> None:
        """Initialise."""
        self.repo = repo
        self.branch_name = branch_name
        self.force = force
        self.push = push
        self.has_stashed = False
        self.old_branch_name = run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def __enter__(self, *_: Any) -> None:
        """Create a new branch."""
        run(
            [
                "docker",
                "run",
                "--rm",
                f"--volume={os.getcwd()}:/src",
                "sbrunner/vim",
                "chown",
                f"{run(['id', '-u'], stdout=subprocess.PIPE).stdout.strip()}:"
                f"{run(['id', '-g'], stdout=subprocess.PIPE).stdout.strip()}",
                "-R",
                ".",
            ],
        )
        for folder in self.repo.get("folders_to_clean") or []:
            shutil.rmtree(folder, ignore_errors=True)
        if self.repo.get("clean", True):
            run(["git", "clean", "-dfX"])
            self.has_stashed = run(["git", "stash", "--all"], check=False).returncode == 0
        else:
            self.has_stashed = run(["git", "stash"], check=False).returncode == 0

        if self.old_branch_name != self.branch_name:
            run(["git", "branch", "--delete", "--force", self.branch_name])
            run(
                ["git", "checkout", "-b", self.branch_name, "--track", f"origin/{self.branch_name}"],
            )
        else:
            run(["git", "pull", "--rebase"])

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Exit."""
        del exc_val, exc_tb

        if exc_type is None and self.push:
            if self.force:
                run(["git", "push", "--force"])
            else:
                run(["git", "push"])

        if self.branch_name != self.old_branch_name:
            run(["git", "checkout", self.old_branch_name])
        if self.has_stashed:
            if run(["git", "stash", "pop"], check=False).returncode != 0:
                run(["git", "reset", "--hard"])
        return False


class Commit:
    """
    Do an commit in a with instruction.

    ```python with Commit("My commit message"):     # Do some changes
    ```
    """

    def __init__(self, commit_message: str) -> None:
        """Initialize."""
        self.commit_message = commit_message

    def __enter__(self, *_: Any) -> None:
        """Do nothing."""

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Commit the changes."""
        del exc_val, exc_tb

        if exc_type is None:
            if not run(["git", "status", "--short"], stdout=subprocess.PIPE).stdout.strip():
                return False
            run(["git", "add", "--all"])
            with tempfile.NamedTemporaryFile() as message_file:
                message_file.write(f"{self.commit_message}\n".encode())
                message_file.flush()
                if run(["git", "commit", f"--file={message_file.name}"], check=False).returncode != 0:
                    run(["git", "add", "--all"])
                    run(["git", "commit", "--no-verify", f"--file={message_file.name}"])
        return False


class Edit:
    r"""
    Edit a file.

    Usage:

    ```python
    with Edit("file.txt") as file:
        file.content = "Header\n" + file.content
    ```
    """

    def __init__(self, filename: str) -> None:
        """Initialize."""
        self.filename = filename
        with open(".github/renovate.json5", encoding="utf-8") as opened_file:
            self.content = opened_file.read()

    def __enter__(self) -> "Edit":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        with open(".github/renovate.json5", "w", encoding="utf-8") as opened_file:
            opened_file.write(self.content)
            return False


class EditYAML:
    """
    Edit a YAML file by keeping the comments, in a with instruction.

    ```python
    with EditYAML("file.yaml") as yaml:
        yaml["key"] = "value"
    ```
    """

    original_data: Optional[str]

    def __init__(self, filename: str, width: int = 110, default_flow_style: bool = False):
        """Initialize the object."""
        self.filename = filename
        self.data: Dict[str, Any] = {}
        self.yaml = YAML()
        self.yaml.default_flow_style = default_flow_style
        self.yaml.width = width  # type: ignore

    def __enter__(self) -> "EditYAML":
        """Load the file."""
        with open(self.filename, encoding="utf-8") as file:
            self.data = self.yaml.load(file)  # nosec
        out = io.StringIO()
        self.yaml.dump(self.data, out)
        self.original_data = out.getvalue()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Save the file if the data has changed."""
        del exc_val, exc_tb
        if exc_type is None:
            out = io.StringIO()
            self.yaml.dump(self.data, out)
            new_data = out.getvalue()
            if new_data != self.original_data:
                with open(self.filename, "w", encoding="utf-8") as file_:
                    file_.write(new_data)
        return False

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


def copy_file(from_: str, to_: str, only_if_already_exists: bool = True) -> None:
    """Copy a file."""
    if os.path.exists(to_):
        os.remove(to_)
        shutil.copyfile(from_, to_)
    elif not only_if_already_exists:
        shutil.copyfile(from_, to_)


def git_grep(text: str, args: Optional[List[str]] = None) -> Set[str]:
    """Grep the code against the text."""
    proc = run(["git", "grep", *(args or []), "--", text], stdout=subprocess.PIPE, encoding="utf-8")
    files = set()
    for line in proc.stdout.split("\n"):
        if line and not line.startswith("Binary file "):
            print(f"{os.getcwd()}/{line}")
            files.add(line.split(":")[0])
    return files


def replace(filename: str, search_text: str, replace_text: str) -> None:
    """Replace the search string by the replace string in the file."""
    with open(filename, encoding="utf-8") as file_:
        content = file_.read()
    content = re.sub(search_text, replace_text, content)
    with open(filename, "w", encoding="utf-8") as file_:
        file_.write(content)


def edit(repo: Repo, files: List[str]) -> None:
    """Edit the files in VSCode."""
    for file in files:
        print(f"{repo['dir']}/{file}")
        with open(f"{repo['dir']}/{file}", "a", encoding="utf-8"):
            pass
        run(["code", f"{repo['dir']}/{file}"])
        print("Press enter to continue")
        input()
        # Remove the file if he is empty
        if os.stat(f"{repo['dir']}/{file}").st_size == 0:
            os.remove(f"{repo['dir']}/{file}")


def update_stabilization_branches(repo: Repo) -> None:
    """
    Update the list of stabilization branches in the repo.

    From the     `SECURITY.md` file.
    """
    import c2cciutils.security  # pylint: disable=import-outside-toplevel

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
        for data in security.data:
            if data[support_index] != "Unsupported" and data[version_index] != repo.get(
                "master_branch", "master"
            ):
                versions.add(data[version_index])
        if versions:
            repo["stabilization_branches"] = list(versions)

    for branch_name in repo.get("stabilization_branches") or []:
        with Branch(repo, branch_name, push=False):
            pass


def do_on_base_branches(
    repo: Repo, branch_prefix: str, func: Callable[[Repo], Optional[List[str]]]
) -> List[str]:
    """Do the func action on all the base branches of the repo."""
    result = set()
    branches = [*(repo.get("stabilization_branches") or []), repo.get("master_branch", "master")]
    for branch in branches:
        create_branch = CreateBranch(
            repo,
            f"{branch_prefix}-{branch}",
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


class App:
    """
    Class that's help to create an application.

    To apply the conversion on all the repositories.
    """

    do_pr = False
    do_pr_on_stabilization_branches = False
    branch_prefix: Optional[str] = None
    args: Any = None
    kwargs: Any = None
    local = False
    one = False

    def __init__(self, repos: List[Repo], action: Callable[[], None], browser: str = "firefox") -> None:
        self.repos = repos
        self.action = action
        self.browser = browser

    def init_pr(self, *args, **kwargs):
        """
        Configure to do create an pull request.

        On the master branch od all the repositories.
        """
        self.do_pr = True
        self.args = args
        self.kwargs = kwargs

    def init_pr_on_stabilization_branches(self, branch_prefix: str, *args, **kwargs):
        """
        Configure to do create an pull request.

        On all the stabilization branches of all the repositories.
        """
        self.do_pr = True
        self.do_pr_on_stabilization_branches = True
        self.branch_prefix = branch_prefix
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        """Run the conversion."""
        if self.local:
            self.action()
            return
        url_to_open = []
        try:
            for repo in self.repos:
                try:
                    print(f"=== {repo['name']} ===")
                    with Cwd(repo):
                        if self.do_pr:
                            base_branches: List[str] = (
                                repo.get("stabilization_branches", [repo.get("master_branch", "master")])
                                if self.do_pr_on_stabilization_branches
                                else [repo.get("master_branch", "master")]
                            )
                            for base_branch in base_branches:
                                self.kwargs["base_branch"] = base_branch
                                if self.do_pr_on_stabilization_branches:
                                    self.kwargs["branch"] = f"{self.branch_prefix}-{base_branch}"
                                create_branch = CreateBranch(repo, *self.args, **self.kwargs)
                                with create_branch:
                                    self.action()
                                if create_branch.pull_request_created:
                                    if create_branch.message:
                                        url_to_open.append(create_branch.message)
                                    else:
                                        url_to_open.append(f"https://github.com/{repo['name']}/pulls")
                                    if self.one:
                                        return
                        else:
                            self.action()
                            if self.one:
                                return
                finally:
                    print(f"=== {repo['name']} ===")
        finally:
            print(f"{len(url_to_open)} pull request created")
            for url in url_to_open:
                run([self.browser, url])
            for url in url_to_open:
                print(url)


def main(
    action: Optional[Callable[[], None]] = None,
    repos_filename: str = "repos.yaml",
    browser: str = "firefox",
    description: str = "Apply an action on all the repos.",
    config: Optional[Dict[str, str]] = None,
) -> None:
    """Apply an action on all the repos."""
    args_parser = argparse.ArgumentParser(description=description)
    args_parser.add_argument("--org", help="The organization to use.")
    args_parser.add_argument("--one", action="store_true", help="Open only one pull request.")
    args_parser.add_argument(
        "--local", action="store_true", help="Run the action locally, don't do any git operations."
    )
    args_parser.add_argument(
        "--repos", default=repos_filename, help="A YAML file that contains the repositories."
    )
    args_parser.add_argument(
        "--browser", default=browser, help="The browser used to open the created pull requests"
    )
    if config is None:
        args_parser.add_argument("--pull-request-branch", help="The pull request branch.")
        args_parser.add_argument("--pull-request-title", help="The pull request title.")
        args_parser.add_argument("--pull-request-body", help="The pull request body.")
        args_parser.add_argument(
            "--pull-request-on-stabilization-branches",
            action="store_true",
            help="To a pull request on all the stabilization branches.",
        )
        args_parser.add_argument("--pull-request-branch-prefix", help="The pull request branch prefix.")
    if action is None:
        args_parser.add_argument("command", help="The command to run.")
    args = args_parser.parse_args()

    if config is None:
        pull_request_on_stabilization_branches = args.pull_request_on_stabilization_branches
        pull_request_title = args.pull_request_title
        pull_request_body = args.pull_request_body
        pull_request_branch = args.pull_request_branch
        pull_request_branch_prefix = args.pull_request_branch_prefix
    else:
        pull_request_on_stabilization_branches = config.get("pull_request_on_stabilization_branches", False)
        pull_request_title = config.get("pull_request_title", None)
        pull_request_body = config.get("pull_request_body", None)
        pull_request_branch = config.get("pull_request_branch", None)
        pull_request_branch_prefix = config.get("pull_request_branch_prefix", None)

    with open(args.repos, encoding="utf-8") as opened_file:
        repos = yaml.load(opened_file.read(), Loader=yaml.SafeLoader)

    if action is None:

        def action() -> List[str]:
            run([args.command])

    app = App(repos, action, browser=args.browser)
    app.one = args.one
    if args.local:
        app.local = True
    elif pull_request_on_stabilization_branches:
        app.init_pr_on_stabilization_branches(
            pull_request_branch_prefix, pull_request_title, pull_request_body
        )
    elif pull_request_branch:
        app.init_pr(pull_request_branch, pull_request_title, pull_request_body)
    app.run()


if __name__ == "__main__":
    main()
