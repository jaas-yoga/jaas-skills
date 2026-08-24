import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from generate_schemas import SCHEMAS_DIR, generate  # noqa: E402


def test_checked_in_schemas_match_models():
    fresh = generate()
    for filename, schema in fresh.items():
        on_disk = json.loads((SCHEMAS_DIR / filename).read_text())
        assert on_disk == schema, (
            f"{filename} is stale — run `uv run python tools/generate_schemas.py`"
        )
