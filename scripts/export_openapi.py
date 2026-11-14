"""Write the API's OpenAPI spec to api/openapi.json.

The committed spec is the contract the hand-written clients (mcp-server/src/
client.py, web/src/api.js, and through the bridge the VS Code and JetBrains
plugins) are checked against in tests/test_contract.py. Regenerate it whenever
you change a route or schema:

    uv run python scripts/export_openapi.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "api" / "openapi.json"


def render() -> str:
    # Importing the app binds an engine; it never connects just to build the spec.
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
    sys.path.insert(0, str(ROOT / "api"))
    from app.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    SPEC.write_text(render())
    print(f"wrote {SPEC.relative_to(ROOT)}")
