# -*- coding: utf-8 -*-
from pathlib import Path

path = Path("scripts/verification.py")
source = path.read_text(encoding="utf-8")
source = source.replace("\nimport requests\n", "\n", 1)
marker = "_PROVIDER_FATAL_ERROR = None\n"
addition = '''_PROVIDER_FATAL_ERROR = None
_REQUESTS_MODULE = getattr(_verification, "requests", None)
_TRANSIENT_REQUEST_ERRORS = tuple(
    cls
    for cls in (
        getattr(_REQUESTS_MODULE, "Timeout", None),
        getattr(_REQUESTS_MODULE, "ConnectionError", None),
    )
    if isinstance(cls, type)
)
'''
if source.count(marker) != 1:
    raise SystemExit(f"marqueur absent ou dupliqué: {source.count(marker)}")
source = source.replace(marker, addition, 1)
old = "except (requests.Timeout, requests.ConnectionError) as exc:"
new = "except _TRANSIENT_REQUEST_ERRORS as exc:"
if source.count(old) != 1:
    raise SystemExit(f"except cible absent ou dupliqué: {source.count(old)}")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
