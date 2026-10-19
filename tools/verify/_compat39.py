"""Check the new modules for syntax that Python 3.9 cannot parse or run.

The upstream package declares ``python_requires=">=3.9"`` but only 3.13 is
installed locally, so compatibility is verified statically:

1. the files must parse with the 3.9 grammar,
2. no ``X | Y`` union may be evaluated eagerly at runtime (PEP 604 landed in
   3.10; with ``from __future__ import annotations`` it is safe inside an
   annotation, but not as a value),
3. no eager builtin generic alias may appear outside an annotation.

Annotation positions are collected explicitly instead of being guessed from the
AST context, because a subscript inside an annotation also has ``Load`` context.
"""

import ast
import sys
from pathlib import Path


FILES = [
    "pathvalidate/batch.py",
    "pathvalidate/_cli.py",
    "pathvalidate/__main__.py",
]

BUILTIN_GENERICS = {"list", "dict", "set", "tuple", "frozenset", "type"}

#: Names whose ``X | Y`` form only works from 3.10 on, when evaluated eagerly.
UNION_OPERANDS = BUILTIN_GENERICS | {
    "int",
    "str",
    "float",
    "bool",
    "bytes",
    "None",
    "NoneType",
}


def _is_builtin_name(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in UNION_OPERANDS
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Attribute):
        return node.attr in UNION_OPERANDS
    return False


def _annotation_nodes(tree: ast.AST) -> set[int]:
    """Collect the id() of every node that sits in a *lazy* annotation position.

    Only annotations covered by ``from __future__ import annotations`` are lazy.
    ``AnnAssign`` annotations on module and class level are lazy as well, but a
    local variable annotation is *not* evaluated at runtime either, so they are
    all treated as lazy. Return annotations are lazy too.
    """

    ids: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            ):
                if arg.annotation is not None:
                    ids.add(id(arg.annotation))

            for arg in (node.args.vararg, node.args.kwarg):
                if arg is not None and arg.annotation is not None:
                    ids.add(id(arg.annotation))

            if node.returns is not None:
                ids.add(id(node.returns))

        if isinstance(node, ast.AnnAssign):
            ids.add(id(node.annotation))

    return ids


def _is_inside_annotation(node: ast.AST, annotation_ids: set[int], parents: dict) -> bool:
    current: ast.AST | None = node

    while current is not None:
        if id(current) in annotation_ids:
            return True
        current = parents.get(id(current))

    return False


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    problems: list[str] = []

    try:
        tree = ast.parse(source, filename=str(path), feature_version=(3, 9))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: not valid Python 3.9 syntax: {exc.msg}"]

    parents: dict[int, ast.AST] = {}

    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    annotation_ids = _annotation_nodes(tree)

    for node in ast.walk(tree):
        if _is_inside_annotation(node, annotation_ids, parents):
            continue

        if isinstance(node, ast.Subscript):
            name = getattr(node.value, "id", None)
            if name in BUILTIN_GENERICS:
                problems.append(
                    f"{path}:{node.lineno}: eager runtime subscript {name}[...] "
                    "(move it into an annotation or use typing.*)"
                )

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            # ``int | None`` evaluated at runtime needs 3.10
            if _is_builtin_name(node.left) or _is_builtin_name(node.right):
                problems.append(
                    f"{path}:{node.lineno}: eager PEP 604 union (needs 3.10 at runtime)"
                )

    return problems


def main() -> int:
    args = sys.argv[1:]

    if args and args[0] == "--file":
        targets = [Path(args[1])]
    else:
        targets = [Path(name) for name in FILES]

    all_problems: list[str] = []

    for target in targets:
        all_problems.extend(check_file(target))

    if all_problems:
        for problem in all_problems:
            print("FAIL", problem)
        return 1

    print(f"ok: {len(targets)} files are Python 3.9 safe (grammar + no eager generics)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
