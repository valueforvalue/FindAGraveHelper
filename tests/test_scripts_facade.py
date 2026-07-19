"""Test that scripts/__init__.py is a docstring-only facade with no eager imports."""

import sys


def test_facade_no_all():
    """scripts.__init__ has no __all__ export list."""
    import scripts

    assert not hasattr(scripts, "__all__"), (
        "scripts.__init__ must not define __all__"
    )


def test_facade_no_eager_imports():
    """Importing scripts must not pull subpackage modules into sys.modules."""
    before = set(sys.modules.keys())
    import scripts  # noqa: F811

    after = set(sys.modules.keys())
    newly_loaded = after - before

    forbidden = {
        "scripts.pipeline.run_unified",
        "scripts.search_fag",
        "scripts.state_normalize",
        "scripts.state.report_generator",
    }
    leaked = newly_loaded & forbidden
    assert not leaked, (
        f"scripts.__init__ eagerly imported: {leaked}"
    )


def test_facade_docstring_only():
    """scripts.__init__ module body is docstring + comments, no executable imports."""
    import ast
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent / "scripts" / "__init__.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)

    # First statement should be the docstring (Expr with Constant/Str)
    # Remaining statements at module level should only be... nothing.
    non_docstring = [
        stmt
        for stmt in tree.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    assert not non_docstring, (
        f"scripts.__init__ has non-docstring statements: "
        f"{[ast.dump(s) for s in non_docstring]}"
    )
