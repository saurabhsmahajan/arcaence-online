import sys
from pathlib import Path

from ingest.loaders import LOADERS

path = Path(sys.argv[1])
loader = LOADERS[path.suffix.lstrip(".").lower()]
for i, unit in enumerate(loader(path), 1):
    print(f"--- unit {i} | section: {unit.section_ref} | page: {unit.page}")
    print(unit.text)
    print()