#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
PARSER_BROWSER = ROOT / "parser_browser"
if str(PARSER_BROWSER) not in sys.path:
    sys.path.insert(0, str(PARSER_BROWSER))

from app.parser.output_contract_validator import validate_output_contract  # noqa: E402
from app.pipeline.stage_registry import build_lovable_contract_reference  # noqa: E402


def _load_json(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Valida contrato Lovable ↔ Parser Python")
    ap.add_argument("--payload", help="document_payload JSON")
    ap.add_argument("--final", help="final_result JSON")
    ap.add_argument("--print-reference", action="store_true", help="imprime referência de contrato/stages")
    ap.add_argument("--out", help="salvar relatório JSON")
    args = ap.parse_args()

    if args.print_reference:
        ref = build_lovable_contract_reference()
        text = json.dumps(ref, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    final = _load_json(args.final)
    payload = _load_json(args.payload)
    report = validate_output_contract(final, payload)
    report.setdefault("lovable_contract_reference", build_lovable_contract_reference())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
