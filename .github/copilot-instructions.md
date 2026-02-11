The `multi_repo_automation/aio_editor.py` contains an asynchronous context manager for editing files. All the io operations must be performed using async functions.

The booth files `multi_repo_automation/aio_editor.py` and `multi_repo_automation/editor.py` should provide the same API, but the former should be implemented using async functions and the latter using sync functions, exceptions:

- `editor.EditRenovateConfig` have no equivalent in `aio_editor`.
- `editor.EditRenovateConfigV2` is named `EditRenovateConfig` in `aio_editor`.

The `README.rst` file should be updated to be able to correctly use this package.

The new functionalities should be reasonably tested.
