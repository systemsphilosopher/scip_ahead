"""
Standalone driver for debugging the indexing pipeline outside of MCP/stdio.

Usage:
    uv run python debug_index.py <language> <repo_root>
    uv run python debug_index.py dotnet "C:\\Git\\systemsphilosopher\\scip_ahead_testbed\\ClassLibrary1"

Run under a debugger (VS Code "Python: Current File", or `uv run python -m pdb debug_index.py ...`)
to step through, or just run it to see full stdout/stderr and where it stalls.
"""
import sys
import time
from scip_ahead.scipper import SCIPper


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    language, repo_root = sys.argv[1], sys.argv[2]
    print(f"[debug] indexing language={language!r} root={repo_root!r}")
    start = time.monotonic()
    result = SCIPper().index(language, repo_root)
    elapsed = time.monotonic() - start
    print(f"[debug] index() returned after {elapsed:.1f}s:\n{result}")


if __name__ == "__main__":
    main()
