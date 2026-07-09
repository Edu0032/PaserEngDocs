from __future__ import annotations

"""SICRO section-aware closure checks for sections A-F (v61.0.40)."""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"

REQUIRED_BY_SECTION = {
    "A": ["codigo", "equipamento", "quantidade"],
    "B": ["codigo", "mao_obra", "quantidade"],
    "C": ["codigo", "material", "quantidade", "unidade", "preco_unitario"],
    "D": ["codigo", "atividade_auxiliar", "quantidade", "unidade", "preco_unitario"],
    "E": ["insumo", "tempo_fixo", "quantidade", "unidade", "preco_unitario"],
    "F": ["insumo", "momento_transporte", "quantidade", "unidade"],
}


def _empty(v: Any) -> bool:
    return v in (None, "")


def validate_sicro_sections(final_result: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    comp = final_result.get("composicoes") if isinstance(final_result.get("composicoes"), dict) else {}
    fam = comp.get("sicro") if isinstance(comp.get("sicro"), dict) else {}
    for collection in ("principais", "auxiliares_globais"):
        blocks = fam.get(collection) if isinstance(fam.get(collection), dict) else {}
        for key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            sicro = block.get("sicro") if isinstance(block.get("sicro"), dict) else {}
            secoes = sicro.get("secoes") if isinstance(sicro.get("secoes"), dict) else {}
            if not secoes:
                issues.append({"code": "sicro_sections_missing", "collection": collection, "block": key})
                continue
            for sec, required in REQUIRED_BY_SECTION.items():
                sec_data = secoes.get(sec) if isinstance(secoes.get(sec), dict) else {}
                rows = sec_data.get("linhas") if isinstance(sec_data, dict) else []
                if rows is None:
                    rows = []
                if not isinstance(rows, list):
                    issues.append({"code": "sicro_section_invalid_rows", "section": sec, "collection": collection, "block": key})
                    continue
                for idx, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    missing = [f for f in required if _empty(row.get(f))]
                    if missing:
                        issues.append({"code": "sicro_section_row_missing_fields", "section": sec, "collection": collection, "block": key, "row_index": idx, "missing_fields": missing})
    return {"version": VERSION, "issues": issues, "issue_count": len(issues)}
