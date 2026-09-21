"""Read a pinned constant out of a source file, as a literal, without importing.

LIC6-FIX-VERIFY V1, mutant M10. A pin is only a pin while the thing that
satisfies it is typed. M10 left every assertion in place and replaced
``ADVISORY_NOTE_AUTHORED``'s dict literal with a comprehension that read the
note's authored lines off disk, so both sides of the equality came from the
same bytes: ``make records`` exited 0, the whole suite stayed green, a false
permissive sentence rendered on two consent screens, and no added line
outside the digest-named blob contained it. The test named after the property
asserted nothing at all.

That cannot be fixed by asserting harder about the imported object, because
the imported object is exactly what the mutant controls. So this does not
import. It parses the source, finds the module-level assignment, and refuses
anything that is not a literal -- a comprehension, a call, a name, a
``dict(...)``, a value assembled at import time. What it returns is what a
reviewer reads in the diff, which is the only thing a pin can be about.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any


class NotALiteral(AssertionError):
    """A pinned constant is computed rather than typed."""


def literal_constant(path: str | os.PathLike[str], name: str) -> Any:
    """The value of module-level ``name`` in ``path``, as written in the file.

    Raises :class:`NotALiteral` when ``name`` is assigned anywhere but once at
    module level, or when what it is assigned is not a literal.
    """
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    found: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                assert node.value is not None
                found.append(node.value)
    if len(found) != 1:
        raise NotALiteral(
            f"{name} is assigned {len(found)} times at module level in "
            f"{path}; a pin is assigned exactly once, or a later assignment "
            "replaces the typed value with a computed one (mutant M10)"
        )
    try:
        return ast.literal_eval(found[0])
    except ValueError as error:
        raise NotALiteral(
            f"{name} in {path} is not a literal. A pin that is computed is "
            "satisfied by whatever computes it, and the test named after the "
            "property becomes a tautology (LIC6-FIX-VERIFY V1, mutant M10). "
            "Type the value."
        ) from error
