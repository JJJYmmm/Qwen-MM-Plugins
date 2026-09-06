"""One-time, behavior-preserving migration of literal TOOL descriptions to handler docstrings.

Dynamic descriptions stay explicit. Refuse handlers with existing docstrings rather than
overwriting developer documentation. Parameter descriptions remain Pydantic-backed.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    count = 0
    for path in sorted((ROOT / "src/capabilities").rglob("*.py")):
        if "vendor" in path.parts:
            continue
        text = path.read_text()
        tree = ast.parse(text)
        assignment = next(
            (
                node
                for node in tree.body
                if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "TOOL")
                or (
                    isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "TOOL" for target in node.targets)
                )
            ),
            None,
        )
        if assignment is None or not isinstance(assignment.value, ast.Dict):
            continue
        entries = [
            (key, value)
            for key, value in zip(assignment.value.keys, assignment.value.values)
            if isinstance(key, ast.Constant) and key.value == "description"
        ]
        if not entries or not isinstance(entries[0][1], ast.Constant):
            continue
        key, value = entries[0]
        handler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle")
        if ast.get_docstring(handler):
            raise ValueError(f"Refusing to replace handler documentation: {path}")
        lines = text.splitlines(keepends=True)
        # All repository TOOL dictionaries use one entry per logical line.
        index = assignment.value.keys.index(key)
        next_key = assignment.value.keys[index + 1] if index + 1 < len(assignment.value.keys) else None
        end = next_key.lineno - 1 if next_key else assignment.end_lineno - 1
        if not "".join(lines[key.lineno - 1 : end]).rstrip().endswith(","):
            raise ValueError(f"Unexpected TOOL dictionary layout: {path}")
        description = value.value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        literal = '    """' + description.replace("\n", "\n    ") + '"""\n'
        lines.insert(handler.body[0].lineno - 1, literal)
        del lines[key.lineno - 1 : end]
        path.write_text("".join(lines))
        count += 1
    print(f"Migrated {count} literal descriptions; dynamic descriptions remain explicit")


if __name__ == "__main__":
    main()
