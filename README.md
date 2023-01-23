# Multi repo automation

## Config

Create a file with something like this:

```yaml
- dir: /home/user/src/myrepo
  name: user/myrepo
  types: ['javascript', 'python', 'docker']
  master_branch: master
  stabilization_branches: [1.0, 1.1]
  folders_to_clean: []
```

## Utilities

```python
import multi_repo_automation as mra

# Test if a file exists
if mra.run(["git", "ls-files", "**/*.txt"], stdout=subprocess.PIPE).stdout.strip() != b"":
  print("Found")
# Test if a file exists and contains a text
if mra.git_grep(file, r"\<text\>"]):
  print("Found")
# Edit a file in vscode
mra.edit("file")
```

## To do something on all repo that not depends on the branch

```python
#!/usr/bin/env python3
import argparse
import multi_repo_automation as mra

def _main() -> None:
    with open(os.path.join(os.path.dirname(__file__), "repo.yaml"), encoding="utf-8") as f:
        repos = yaml.load(f.read(), Loader=yaml.SafeLoader)

    args_parser = argparse.ArgumentParser(description="Apply an action on all the repos.")
    args = args_parser.parse_args()

    pull_request_created_message = []
    try:
        for repo in repos:
                try:
                    print(f"=== {repo['name']} ===")
                    with mra.Cwd(repo):
                        # Do something
                finally:
                    print(f"=== {repo['name']} ===")
    finally:
        print(f"{len(pull_request_created_message)} pull request created")
        for repo in pull_request_created_message:
            print(repo)

if __name__ == '__main__':
  _main()
```

## To update all the master branches write a script like

```python
#!/usr/bin/env python3
import argparse
import multi_repo_automation as mra

def _main() -> None:
    with open(os.path.join(os.path.dirname(__file__), "repo.yaml"), encoding="utf-8") as f:
        repos = yaml.load(f.read(), Loader=yaml.SafeLoader)

    args_parser = argparse.ArgumentParser(description="Apply an action on all the repos.")
    args = args_parser.parse_args()

    pull_request_created_message = []
    try:
        for repo in repos:
                try:
                    print(f"=== {repo['name']} ===")
                    with mra.Cwd(repo):
                        pull_request_created_message.extend(_do(repo))
                finally:
                    print(f"=== {repo['name']} ===")
    finally:
        print(f"{len(pull_request_created_message)} pull request created")
        for repo in pull_request_created_message:
            print(repo)

if __name__ == '__main__':
  _main()

def _do(repo: mra.Repo) -> List[str]:
    create_branch = mra.CreateBranch(
        repo,
        "branch_name",
        "Commit/Pull request message",
    )
    with create_branch:
        # Do something

    if create_branch.pull_request_created:
        if create_branch.message:
            return [create_branch.message]
        else:
            return [f"https://github.com/{repo['name']}/pulls"]
  return []
```

## To update all the stabilization branches write a script like

```python
#!/usr/bin/env python3
import argparse
import multi_repo_automation as mra

def _main() -> None:
    with open(os.path.join(os.path.dirname(__file__), "repo.yaml"), encoding="utf-8") as f:
        repos = yaml.load(f.read(), Loader=yaml.SafeLoader)

    args_parser = argparse.ArgumentParser(description="Apply an action on all the repos.")
    args = args_parser.parse_args()

    pull_request_created_message = []
    try:
        for repo in repos:
                try:
                    print(f"=== {repo['name']} ===")
                    with mra.Cwd(repo):
                        pull_request_created_message.extend(
                          do_on_base_branches(repo:, 'branch_prefix' , _do)
                finally:
                    print(f"=== {repo['name']} ===")
    finally:
        print(f"{len(pull_request_created_message)} pull request created")
        for repo in pull_request_created_message:
            print(repo)

if __name__ == '__main__':
  _main()

def _do(repo: mra.Repo) -> List[str]:
    create_branch = mra.CreateBranch(
        repo,
        "branch_name",
        "Commit/Pull request message",
    )
    with create_branch:
        # Do something

    if create_branch.pull_request_created:
        if create_branch.message:
            return [create_branch.message]
        else:
            return [f"https://github.com/{repo['name']}/pulls"]
  return []
```
