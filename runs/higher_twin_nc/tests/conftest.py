import sys
from pathlib import Path

# The experiment is an isolated, flat module tree; make it importable when
# pytest runs from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
