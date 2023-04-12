"""Tools to automated changes on multiple repositories."""

import argparse
import os
import re
import shutil
import subprocess  # nosec
import tempfile
import traceback
from distutils.version import (  # pylint: disable=deprecated-module,useless-suppression
    LooseVersion,
)
from types import TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    TypedDict,
    cast,
)

import requests
import yaml
from identify import identify

from multi_repo_automation.editor import Edit  # noqa
from multi_repo_automation.editor import EditConfig  # noqa
from multi_repo_automation.editor import EditTOML  # noqa
from multi_repo_automation.editor import EditYAML  # noqa
from multi_repo_automation.editor import add_pre_commit_hook  # noqa
from multi_repo_automation.tools import run

CONFIG_FILENAME = "multi-repo-automation.yaml"

if "APPDATA" in os.environ:
    CONFIG_FOLDER = os.environ["APPDATA"]
elif "XDG_CONFIG_HOME" in os.environ:
    CONFIG_FOLDER = os.environ["XDG_CONFIG_HOME"]
else:
    CONFIG_FOLDER = os.path.expanduser("~/.config")

CONFIG_PATH = os.path.join(CONFIG_FOLDER, CONFIG_FILENAME)


class Repo(TypedDict, total=False):
    """The repository description."""

    dir: str
    name: str
    master_branch: str
    stabilization_branches: List[str]
    folders_to_clean: List[str]
    clean: bool


_BROWSER = "xdg-open"


def get_browser() -> str:
    """Get the global configuration."""
    return _BROWSER


_EDITOR = "xdg-open"


def get_editor() -> str:
    """Get the global configuration."""
    return _EDITOR


_REPO_CONFIG: Repo = {}


def get_repo_config() -> Repo:
    """Get the repository configuration."""
    return _REPO_CONFIG


_ARGUMENTS: Optional[argparse.Namespace] = None


def get_arguments() -> argparse.Namespace:
    """Get the global arguments."""

    assert _ARGUMENTS is not None
    return _ARGUMENTS


def all_filenames(repo: Optional[Repo] = None) -> List[str]:
    """Get all the filenames of the repository."""
    cmd = ["git", "ls-files"]
    result = (
        run(cmd, stdout=subprocess.PIPE)
        if repo is None
        else run(cmd, cwd=repo["dir"], stdout=subprocess.PIPE)
    )
    return result.stdout.strip().split("\n")


def all_identify(repo: Optional[Repo] = None) -> Set[str]:
    """Get all the types of the repository."""
    result: Set[str] = set()
    for filename in all_filenames(repo):
        result |= identify.tags_from_path(filename)
    return result


def all_filenames_identify(type_: str, repo: Optional[Repo] = None) -> List[str]:
    """Check if the repository contains a file of the given type."""
    result = []
    for filename in all_filenames(repo):
        if type_ in identify.tags_from_path(filename):
            result.append(filename)
    return result


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
        del exc_tb

        if exc_type is not None:
            print("=" * 30)
            print(type(self).__name__)
            print(exc_type.__name__)
            print(exc_val)
            traceback.print_exc()

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
        pull_request_body: Optional[str] = None,
    ) -> None:
        """Initialize."""
        self.repo = repo
        if base_branch is None:
            base_branch = repo.get("master_branch", "master")
        self.base_branch = base_branch
        self.new_branch_name = new_branch_name
        self.commit_message = commit_message
        self.pull_request_body = pull_request_body
        self.force = force
        self.has_stashed = False
        self.pull_request_created = False
        self.old_branch_name = run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def __enter__(self, *_: Any) -> None:
        """Create the branch."""
        for folder in self.repo.get("folders_to_clean") or []:
            shutil.rmtree(folder, ignore_errors=True)
        if self.repo.get("clean", True):
            run(["git", "clean", "-dfX"], auto_fix_owner=True)
            proc = run(
                ["git", "stash", "--all", "--message=Stashed by multi repo automation"],
                stdout=subprocess.PIPE,
                exit_on_error=False,
            )
            self.has_stashed = proc.stdout.strip() != "No local changes to save"
        else:
            proc = run(["git", "stash"], stdout=subprocess.PIPE, encoding="utf-8", env={})
            self.has_stashed = proc.stdout.strip() != "No local changes to save"
        run(["git", "fetch"])
        run(["git", "checkout", self.repo.get("master_branch") or "master"])
        if self.new_branch_name == self.old_branch_name:
            run(["git", "reset", "--hard", f"origin/{self.base_branch}", "--"])
        else:
            run(["git", "branch", "--delete", "--force", self.new_branch_name], False)
            run(
                [
                    "git",
                    "checkout",
                    "-b",
                    self.new_branch_name,
                    f"origin/{self.base_branch}",
                ],
                auto_fix_owner=True,
            )
        run(["git", "status"])

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Literal[False]:
        """Create the pull request."""
        del exc_tb

        if exc_type is not None:
            print("=" * 30)
            print(type(self).__name__)
            print(exc_type.__name__)
            print(exc_val)
            traceback.print_exc()

        if self.commit_message and exc_type is None:
            self.pull_request_created, self.message = create_pull_request(
                self.repo,
                self.commit_message,
                force=self.force,
                base_branch=self.base_branch,
                body=self.pull_request_body,
            )
        if self.new_branch_name != self.old_branch_name:
            run(["git", "checkout", self.old_branch_name, "--"])
        if self.has_stashed:
            if run(["git", "stash", "pop"], False).returncode != 0:
                run(["git", "reset", "--hard"])
        return False


def create_pull_request(
    repo: Repo,
    title: Optional[str] = None,
    commit: bool = True,
    label: Optional[str] = None,
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
        f"--base={base_branch}",
    ]
    if label:
        cmd.append(f"--label={label}")
    if commit:
        run(["git", "add", "--all"])
        assert title is not None  # nosec
        with tempfile.NamedTemporaryFile() as message_file:
            message_file.write(f"{title}\n".encode())
            if body is not None:
                message_file.write(f"\n{body}\n".encode())
            message_file.flush()
            if run(["git", "commit", f"--file={message_file.name}"], False).returncode != 0:
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
    branch_name = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout=subprocess.PIPE).stdout.strip()
    run(
        [
            "git",
            "branch",
            f"--set-upstream-to=origin/{branch_name}",
            branch_name,
        ],
    )

    url_proc = run(cmd, False, stdout=subprocess.PIPE)
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
        for folder in self.repo.get("folders_to_clean") or []:
            shutil.rmtree(folder, ignore_errors=True)
        if self.repo.get("clean", True):
            run(["git", "clean", "-dfX"])
            self.has_stashed = run(["git", "stash", "--all"], False).returncode == 0
        else:
            self.has_stashed = run(["git", "stash"], False).returncode == 0

        if self.old_branch_name != self.branch_name:
            run(["git", "branch", "--delete", "--force", self.branch_name], False)
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
        del exc_tb

        if exc_type is not None:
            print("=" * 30)
            print(type(self).__name__)
            print(exc_type.__name__)
            print(exc_val)
            traceback.print_exc()

        if exc_type is None and self.push:
            if self.force:
                run(["git", "push", "--force"])
            else:
                run(["git", "push"])

        if self.branch_name != self.old_branch_name:
            run(["git", "checkout", self.old_branch_name])
        if self.has_stashed:
            if run(["git", "stash", "pop"], False).returncode != 0:
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
        del exc_tb

        if exc_type is not None:
            print("=" * 30)
            print(type(self).__name__)
            print(exc_type.__name__)
            print(exc_val)
            traceback.print_exc()

        if exc_type is None:
            if not run(["git", "status", "--short"], stdout=subprocess.PIPE).stdout.strip():
                return False
            run(["git", "add", "--all"])
            with tempfile.NamedTemporaryFile() as message_file:
                message_file.write(f"{self.commit_message}\n".encode())
                message_file.flush()
                if run(["git", "commit", f"--file={message_file.name}"], False).returncode != 0:
                    run(["git", "add", "--all"])
                    run(["git", "commit", "--no-verify", f"--file={message_file.name}"])
        return False


def copy_file(from_: str, to_: str, only_if_already_exists: bool = True) -> None:
    """Copy a file."""
    if os.path.exists(to_):
        os.remove(to_)
        shutil.copyfile(from_, to_)
    elif not only_if_already_exists:
        shutil.copyfile(from_, to_)


def git_grep(text: str, args: Optional[List[str]] = None) -> Set[str]:
    """Grep the code against the text."""
    proc = run(
        ["git", "grep", *(args or []), "--", text],
        exit_on_error=False,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
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


def edit(files: List[str]) -> None:
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


def update_stabilization_branches(repo: Repo) -> None:
    """
    Update the list of stabilization branches in the repo.

    From the     `SECURITY.md` file.
    """
    import c2cciutils.security  # pylint: disable=import-outside-toplevel

    security_response = requests.get(
        f"https://raw.githubusercontent.com/{repo['name']}/{repo.get('master_branch', 'master')}/SECURITY.md",
        headers=c2cciutils.add_authorization_header({}),
        timeout=30,
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
            version_list = list(versions)
            version_list.sort(key=LooseVersion)
            repo["stabilization_branches"] = version_list


def do_on_base_branches(
    repo: Repo, branch_prefix: str, func: Callable[[Repo], Optional[List[str]]]
) -> List[str]:
    """Do the func action on all the base branches of the repo."""
    result = set()
    branches = [*(repo.get("stabilization_branches") or []), repo.get("master_branch", "master")]
    for branch in branches:
        create_branch = CreateBranch(
            repo,
            f"{branch_prefix.rstrip('-')}-{branch}",
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
    kwargs: Any = None
    local = False
    one = False
    repository_prefix: Optional[str] = None

    def __init__(self, repos: List[Repo], action: Callable[[], None], browser: str = "firefox") -> None:
        self.repos = repos
        self.action = action
        self.browser = browser

    def init_pr(self, **kwargs: Any) -> None:
        """
        Configure to do create an pull request.

        On the master branch od all the repositories.
        """
        self.do_pr = True
        self.kwargs = kwargs

    def init_pr_on_stabilization_branches(self, branch_prefix: str, **kwargs: Any) -> None:
        """
        Configure to do create an pull request.

        On all the stabilization branches of all the repositories.
        """
        self.do_pr = True
        self.do_pr_on_stabilization_branches = True
        self.branch_prefix = branch_prefix
        self.kwargs = kwargs

    def run(self) -> None:
        """Run the conversion."""
        global _REPO_CONFIG  # pylint: disable=global-statement

        if self.local:
            self.action()
            return
        url_to_open = []
        try:
            for repo in self.repos:
                _REPO_CONFIG = repo
                if self.repository_prefix is None or repo["name"].startswith(self.repository_prefix):
                    try:
                        print(f"=== {repo['name']} ===")
                        with Cwd(repo):
                            if self.do_pr:
                                base_branches: Set[str] = {repo.get("master_branch", "master")}
                                if self.do_pr_on_stabilization_branches:
                                    base_branches.update(repo.get("stabilization_branches") or [])

                                for base_branch in base_branches:
                                    self.kwargs["base_branch"] = base_branch
                                    if self.do_pr_on_stabilization_branches:
                                        assert self.branch_prefix is not None
                                        self.kwargs[
                                            "new_branch_name"
                                        ] = f"{self.branch_prefix.rstrip('-')}-{base_branch}"
                                    create_branch = CreateBranch(repo, **self.kwargs)
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
    description: str = "Apply an action on all the pre-configured repositories.",
    config: Optional[Dict[str, str]] = None,
    add_arguments: Optional[Callable[[argparse.ArgumentParser], None]] = None,
) -> None:
    """Apply an action on all the repos."""

    config = config or {}
    user_config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as config_file:
            user_config = yaml.load(config_file, Loader=yaml.SafeLoader)
    repos_filename: str = user_config.get("repos_filename", "repos.yaml")

    args_parser = argparse.ArgumentParser(description=description)
    args_parser_local = args_parser.add_argument_group("local", "To apply the action locally.")
    args_parser_local.add_argument("--local", action="store_true", help="Enable it.")

    args_parser_repos = args_parser.add_argument_group(
        "repos", "Option used to browse all the repositories, and create pull request with the result."
    )
    args_parser_repos.add_argument(
        "--repositories", default=repos_filename, help="A YAML file that contains the repositories."
    )
    args_parser_repos.add_argument("--repository-prefix", help="Apply on repository with prefix.")
    args_parser_repos.add_argument("--one", action="store_true", help="Open only one pull request.")
    args_parser_repos.add_argument(
        "--pull-request-title", help="The pull request title.", default=config.get("pull_request_title", None)
    )
    args_parser_repos.add_argument(
        "--pull-request-body", help="The pull request body.", default=config.get("pull_request_body", None)
    )
    args_parser_master = args_parser.add_argument_group(
        "master", "To apply the action on all master branches."
    )
    args_parser_master.add_argument(
        "--branch", help="The created branch branch name.", default=config.get("branch", None)
    )
    args_parser_stabilization = args_parser.add_argument_group(
        "stabilization", "To apply the action on all stabilization (including master) branches."
    )
    if "pull_request_on_stabilization_branches" not in config:
        args_parser_stabilization.add_argument(
            "--on-stabilization-branches",
            action="store_true",
            help="Enable it.",
        )
    args_parser_stabilization.add_argument(
        "--branch-prefix",
        help="The created branch prefix.",
        default=config.get("pull_request_branch_prefix", None),
    )
    args_parser_repos.add_argument(
        "--browser",
        default=user_config.get("browser", "xdg-open"),
        help="The browser used to open the created pull requests",
    )
    args_parser_repos.add_argument(
        "--editor", default=user_config.get("editor", "xdg-open"), help="The editor used to open the files"
    )
    if action is None:
        args_parser.add_argument("command", help="The command to run.")

    if add_arguments is not None:
        add_arguments(args_parser)

    args = args_parser.parse_args()
    global _ARGUMENTS  # pylint: disable=global-statement
    _ARGUMENTS = args

    pull_request_on_stabilization_branches = (
        config["pull_request_on_stabilization_branches"]
        if "pull_request_on_stabilization_branches" in config
        else args.on_stabilization_branches
    )
    pull_request_title = args.pull_request_title
    pull_request_body = args.pull_request_body
    pull_request_branch = args.branch
    pull_request_branch_prefix = args.branch_prefix

    repos = []
    if not args.local:
        with open(args.repositories, encoding="utf-8") as opened_file:
            repos = yaml.load(opened_file.read(), Loader=yaml.SafeLoader)

    if action is None:

        def action() -> None:
            run([args.command])

    global _BROWSER  # pylint: disable=global-statement
    _BROWSER = args.browser

    global _EDITOR  # pylint: disable=global-statement
    _EDITOR = args.editor

    app = App(repos, action, browser=args.browser)
    app.one = args.one
    app.repository_prefix = args.repository_prefix
    if args.local:
        app.local = True
    elif pull_request_on_stabilization_branches:
        app.init_pr_on_stabilization_branches(
            branch_prefix=pull_request_branch_prefix,
            commit_message=pull_request_title,
            pull_request_body=pull_request_body,
        )
    elif pull_request_branch:
        app.init_pr(
            new_branch_name=pull_request_branch,
            commit_message=pull_request_title,
            pull_request_body=pull_request_body,
        )
    app.run()


def update_stabilization_branches_main() -> None:
    """Update the stabilization branches."""
    user_config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as config_file:
            user_config = yaml.load(config_file, Loader=yaml.SafeLoader)
    repos_filename: str = user_config.get("repos_filename", "repos.yaml")

    args_parser = argparse.ArgumentParser(description="Update the stabilization branches.")
    args_parser.add_argument(
        "--repositories", default=repos_filename, help="A YAML file that contains the repositories."
    )
    args_parser.add_argument("--diff", action="store_true", help="Only show the diff")
    args = args_parser.parse_args()

    with EditYAML(args.repositories, diff=args.diff, run_pre_commit=False) as repos:
        assert isinstance(repos, EditYAML)
        for repo in repos:
            update_stabilization_branches(cast(Repo, repo))
