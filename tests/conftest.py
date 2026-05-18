import sys
from pathlib import Path

# Make scripts/check_dependencies.py importable as a regular module.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
