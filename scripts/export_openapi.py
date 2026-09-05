import json
from pathlib import Path

from services.api.main import app

target = Path(__file__).resolve().parents[1] / "packages/contracts/openapi.json"
target.write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
    newline="\n",
)
