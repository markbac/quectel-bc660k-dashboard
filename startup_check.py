"""Explain a failed ``ctxlogkit`` import in terms the user can act on."""
import importlib.util
from typing import Optional

INSTALL = 'pip install "ctxlogkit @ git+https://github.com/markbac/py-logkit"'


def ctxlogkit_help(error: Optional[BaseException] = None) -> str:
    """Return a message saying why ``ctxlogkit`` could not be imported and how to fix it.

    Two causes are told apart. A folder named ``ctxlogkit`` with no code in it
    (for example an empty directory next to ``server.py``) hides the real
    package, and the import then fails with "unknown location".
    Otherwise the package is simply not installed.
    """
    spec = importlib.util.find_spec("ctxlogkit")
    lines = ["Cannot start: the ctxlogkit logging package could not be imported."]
    if spec is not None and spec.origin is None:
        folders = ", ".join(spec.submodule_search_locations or [])
        lines += [
            f"A folder named 'ctxlogkit' with no code in it is hiding the package: {folders}",
            "Delete that folder, then run again.",
        ]
    else:
        lines += [
            "It is not installed in this Python environment. Install the project's requirements:",
            "    pip install -r requirements.txt",
            "or just the logger:",
            f"    {INSTALL}",
            "On Windows, run_dashboard.ps1 does all of this for you.",
        ]
    if error is not None:
        lines.append(f"(Python said: {error})")
    return "\n".join(lines)
