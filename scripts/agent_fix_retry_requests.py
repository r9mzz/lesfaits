# -*- coding: utf-8 -*-
from pathlib import Path

path = Path("scripts/verification.py")
source = path.read_text(encoding="utf-8")
old_import = "import re\nimport sys\n"
new_import = "import re\nimport sys\n\nimport requests\n"
if source.count(old_import) != 1:
    raise SystemExit(f"imports cibles absents ou dupliqués: {source.count(old_import)}")
source = source.replace(old_import, new_import, 1)
old_except = "except (_verification.requests.Timeout, _verification.requests.ConnectionError) as exc:"
new_except = "except (requests.Timeout, requests.ConnectionError) as exc:"
if source.count(old_except) != 1:
    raise SystemExit(f"except cible absent ou dupliqué: {source.count(old_except)}")
path.write_text(source.replace(old_except, new_except, 1), encoding="utf-8")
