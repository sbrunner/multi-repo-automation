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
if mra.run(["git", "ls-files", "**/*.txt"], stdout=subprocess.PIPE).stdout.strip() != "":
  print("Found")
# Get all YAML files:
mra.all_filenames_identify("yaml")
# Test if a file exists and contains a text
if mra.git_grep(file, r"\<text\>"]):
  print("Found")
# Edit a file in vscode
mra.edit("file")
```

## Genenric run

```python
#!/usr/bin/env python3
import multi_repo_automation as mra


def _do() -> None:
    # Do something
    pass

if __name__ == "__main__":
    mra.main(_do)
```

In the \_do function do the changes you want in your repo.

Use the `--help` option to see the available options.

## To update all the master branches write a script like

```python
#!/usr/bin/env python3
import multi_repo_automation as mra

def _do() -> None:
    # Do something
    pass

if __name__ == "__main__":
    mra.main(
        _do,
        os.path.join(os.path.dirname(__file__), "repo.yaml"),
        "/home/sbrunner/bin/firefox/firefox",
        config={
            "pull_request_branch": "branch_name",
            "pull_request_title": "Commit/Pull request message",
            "pull_request_body": "Optional body",
        },
    )
```

## To update all the stabilization branches write a script like

```python
#!/usr/bin/env python3
import multi_repo_automation as mra

def _do() -> None:
    # Do something
    pass

if __name__ == "__main__":
    mra.main(
        _do,
        os.path.join(os.path.dirname(__file__), "repo.yaml"),
        "/home/sbrunner/bin/firefox/firefox",
        config={
            "pull_request_on_stabilization_branches": True,
            "pull_request_branch_prefix": "prefix",
            "pull_request_title": "Commit/Pull request message",
            "pull_request_body": "Optional body",
        },
    )
```

## Configuration

The configuration is a YAML file `~/.config/multi-repo-automation.yaml` with the following options:

`repos_filename`: the filename of the files with the repositories definitions, default is `repos.yaml`.
`browser`: the browser to use to open the pull requests, default is `xdg-open`.
