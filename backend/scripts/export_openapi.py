import json
import os
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

for name in tuple(os.environ):
    if name.startswith("ANIMETRON_"):
        del os.environ[name]

from app.main import api


print(json.dumps(api.openapi(), sort_keys=True))
