import ast
import sys


def get_functions(filename):
    with open(filename) as f:
        tree = ast.parse(f.read())
    funcs = [
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef) or isinstance(n, ast.AsyncFunctionDef)
    ]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    for c in classes:
        funcs.extend(
            [
                f"{c.name}.{n.name}"
                for n in c.body
                if isinstance(n, ast.FunctionDef) or isinstance(n, ast.AsyncFunctionDef)
            ]
        )
    return funcs


print(get_functions(sys.argv[1]))
