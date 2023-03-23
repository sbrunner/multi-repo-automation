# Multi repo automation

## Configuration

To be able to apply your changes on multiple repository you should create a file with something like this:

```yaml
- dir: /home/user/src/my-repo
  name: user/my-repo
  types: ['javascript', 'python', 'docker']
  master_branch: master
  stabilization_branches: [1.0, 1.1]
  folders_to_clean: []
```

The main configuration is a YAML file `~/.config/multi-repo-automation.yaml` with the following options:

`repos_filename`: the filename of the files with the repositories definitions create above, default is `repos.yaml`.
`browser`: the browser to use to open the pull requests, default is `xdg-open`.
`editor`: the editor to use to edit files, default is `xdg-open`.

## Migration script base

```python
#!/usr/bin/env python3

import multi_repo_automation as mra

def _do() -> None:
    # Your actions

if __name__ == "__main__":
    mra.main(
        _do,
        config={
        # pull_request_on_stabilization_branches: To apply the action on all stabilization (including master) branches.
        # pull_request_title: The pull request title.
        # pull_request_body: The pull request body.
        # branch: The created branch branch name.
        # pull_request_branch_prefix: The created branch prefix (used when we run it on all the stabilization branches).
        },
    )
```

Use the `--help` option to see the available options.

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
# Edit a files manually
mra.edit(["file"])
```

### Edit file programmatically

```python
   with mra.Edit('my-file.txt') as edit:
      edit.content = edit.content.replace('<from>', '<to>')
```

### Edit YAML file programmatically

```python
   with mra.EditYAML('my-file.yaml') as edit:
      edit.setdefault('dict', {})['prop'] = 'value'
```

### Edit TOML file programmatically

```python
   with mra.EditTOML('my-file.toml') as edit:
      edit.setdefault('dict', {})['prop'] = 'value'
```

### Edit Config file programmatically

```python
   with mra.EditConfigL('my-file.ini') as edit:
      edit.setdefault('dict', {})['prop'] = 'value'
```

## Contributing

Install the pre-commit hooks:

```bash
pip install pre-commit
pre-commit install --allow-missing-config
```
