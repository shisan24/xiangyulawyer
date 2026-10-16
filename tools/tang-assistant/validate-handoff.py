#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Validate delegate_task output against handoff schema."""
import json, sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "delegate-handoff.schema.json"

def validate_handoff(data: dict) -> list[str]:
    """Validate against schema. Returns list of errors (empty = valid)."""
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    errors = []
    required = schema.get("required", [])
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")
    if "status" in data and data["status"] not in schema["properties"]["status"]["enum"]:
        errors.append(f"Invalid status: {data['status']}")
    if "summary" in data and len(str(data["summary"])) < 10:
        errors.append("Summary too short (<10 chars)")
    return errors

if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.loads(sys.stdin.read())
    errors = validate_handoff(data)
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
        sys.exit(1)
    print("✅ Valid handoff")
