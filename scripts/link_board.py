"""Put the project board URL into the scope statement and team contract, then rebuild the PDFs if pdflatex exists.

Usage: python3 scripts/link_board.py https://github.com/users/<owner>/projects/<n>/views/<v>
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"
ROWS = {
    "scope.tex": r"Project board & \url{%s} (GitHub Projects kanban: Backlog, To Do, In Progress, Review, Done; code repository kept private) \\",
    "team_contract.tex": r"Project board & \url{%s} (GitHub Projects kanban board; code repository kept private) \\",
}


def main(url: str) -> None:
    if not re.match(r"^https://github\.com/(users|orgs)/[^/]+/projects/\d+", url):
        sys.exit(f"Not a GitHub Projects URL: {url}")
    for name, row in ROWS.items():
        p = DOCS / name
        text = p.read_text()
        new, n = re.subn(r"^Project board & .*\\\\$", lambda _m: row % url, text, count=1, flags=re.M)
        if n != 1:
            sys.exit(f"No 'Project board &' row found in {p}")
        p.write_text(new)
        print(f"Linked board in docs/{name}")
    if shutil.which("pdflatex"):
        for name in ROWS:
            for _ in range(2):
                subprocess.run(["pdflatex", "-interaction=nonstopmode", name], cwd=DOCS,
                               stdout=subprocess.DEVNULL, check=False)
        print("Rebuilt PDFs in docs/")
    else:
        print("pdflatex not found: the CI workflow builds the updated PDFs (Actions > latest run > artifacts).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
