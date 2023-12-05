"""Convert YAML to Python, with comment (for ruamel)."""

import argparse
import sys
from io import StringIO
from typing import Any, Union

import ruamel.yaml


def commented_sec(value: list[Union[tuple[Any], tuple[Any, str]]]) -> ruamel.yaml.comments.CommentedSeq:
    """Get a commented list (for ruamel)."""
    result = ruamel.yaml.comments.CommentedSeq([v[0] for v in value])
    for key, val in enumerate(value):
        if len(val) == 2:
            _, comment = val
            result.yaml_add_eol_comment(comment, key)
            result.ca.items[key][0].value = comment
    return result


def commented_map(
    value: dict[str, Union[tuple[Any], tuple[Any, str], tuple[Any, str, int]]]
) -> ruamel.yaml.comments.CommentedMap:
    """Get a commented dictionary (for ruamel)."""
    result = ruamel.yaml.comments.CommentedMap({k: v[0] for k, v in value.items()})
    for key, val in value.items():
        if len(val) != 1:
            if len(val) == 2:
                val = (val[0], val[1], 0)
            _, comment, index = val
            result.yaml_add_eol_comment(comment, key)
            result.ca.items[key][2].value = comment
            if index == 3:
                result.ca.items[key][2].column += 2
                result.ca.items[key] = [None, None, None, [result.ca.items[key][2]]]
    return result


def folder_scalar_string(value: list[str]) -> ruamel.yaml.scalarstring.FoldedScalarString:
    """
    Get a folded scalar string (for ruamel).

    Example of use:
    folder_scalar_string(["test1", "test2"])
    =>
    key: >-
      test1
      test2
    """
    result = ruamel.yaml.scalarstring.FoldedScalarString(" ".join(value))
    result.fold_pos = []  # type: ignore[attr-defined]
    pos = -1
    for line in value:
        if pos >= 0:
            result.fold_pos.append(pos)  # type: ignore[attr-defined]
        pos += len(line) + 1
    return result


def get_python(value: Any, prefix: str = "") -> str:
    """Convert a YAML object to a Python object."""
    if isinstance(value, dict):
        if value.ca.items:  # type: ignore[attr-defined]
            comments = {}
            for k, comments_ in value.ca.items.items():  # type: ignore[attr-defined]
                for index, comment in enumerate(comments_):
                    if comment is not None:
                        if isinstance(comment, list):
                            comments[k] = [comment[0].value, index]
                        else:
                            comments[k] = [comment.value, index]
            result = ["mra_yaml.commented_map({"]
            for key, val in value.items():
                if key in comments:
                    result += [
                        f'{prefix}    "{key}": [',
                        f'{prefix}        {get_python(val, prefix + "        ")},',
                        f"{prefix}        {repr(comments[key][0])},",
                    ]
                    if comments[key][1] == 3:
                        result.append(f"{prefix}        {repr(comments[key][1])},")
                    result.append(f"{prefix}    ],")
                else:
                    result.append(
                        f'{prefix}    "{key}": [{get_python(val, prefix + "        ")}],',
                    )
            result.append(f"{prefix}}})")
            return "\n".join(result)
        return "\n".join(
            [
                "{",
                *[
                    f'{prefix}    "{key}": {get_python(value, prefix + "    ")},'
                    for key, value in value.items()
                ],
                f"{prefix}}}",
            ]
        )

    if isinstance(value, list):
        if value.ca.items:  # type: ignore[attr-defined]
            comments = {}
            for k, comments_ in value.ca.items.items():  # type: ignore[attr-defined]
                for index, comment in enumerate(comments_):
                    if comment is not None:
                        if isinstance(comment, list):
                            comments[k] = [comment[0].value, index]
                        else:
                            comments[k] = [comment.value, index]

            result = ["mra_yaml.commented_sec(["]
            for key, val in enumerate(value):
                if key in comments:
                    result += [
                        f"{prefix}    [",
                        f'{prefix}        {get_python(val, prefix + "    ")},',
                        f"{prefix}        {repr(comments[key][0])},",
                        f"{prefix}    ],",
                    ]
                else:
                    result.append(f'{prefix}    [{get_python(val, prefix + "    ")}],')

            result.append(f"{prefix}])")
            return "\n".join(result)
        return "\n".join(
            [
                "[",
                *[f"{prefix}    {get_python(value, prefix + '    ')}," for value in value],
                f"{prefix}]",
            ]
        )

    return repr(value)


def _test() -> Any:
    txt_doc = """dict:
  # line 11
  aa: 11
  # line 22
  bb: 22

  # line 33
  cc: 33
  # line 44
  dd: 44

seq:
  # line 11
  - 11
  # line 22
  - 22

  # line 33
  - 33
  # line 44
  - 44
"""
    yaml = ruamel.yaml.YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    document = yaml.load(txt_doc)
    python = get_python(document)
    import multi_repo_automation.commented_yaml as mra_yaml  # pylint: disable=import-outside-toplevel, unused-import,import-self

    obj = eval(python)  # pylint: disable=eval-used # nosec
    new_doc = StringIO()
    yaml.dump(obj, new_doc)
    print(new_doc.getvalue())
    assert new_doc.getvalue() == txt_doc


def main() -> Any:
    """Convert YAML to Python, with comment."""
    parser = argparse.ArgumentParser(
        "Convert YAML to Python, with comment (for ruamel)", usage="cat file.yaml > %(prog)s -"
    )
    parser.add_argument("document", help="YAML document to convert")
    parser.add_argument("--test", action="store_true", help="Test the conversion")
    arguments = parser.parse_args()

    if arguments.test:
        _test()
        return

    yaml = ruamel.yaml.YAML()
    document = yaml.load(sys.stdin) if arguments.document == "-" else yaml.load(arguments.document)

    print("import multi_repo_automation.commented_yaml as mra_yaml")
    print()

    print(get_python(document))


if __name__ == "__main__":
    main()
