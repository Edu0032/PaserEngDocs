from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

VERSION = "v61.0.35-candidate-profile-consensus-engine"


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\u00a0", " ").split()).strip()


def _norm(v: Any) -> str:
    text = _clean(v).upper()
    repl = str.maketrans({"Á":"A","À":"A","Â":"A","Ã":"A","É":"E","Ê":"E","Í":"I","Ó":"O","Ô":"O","Õ":"O","Ú":"U","Ç":"C"})
    return text.translate(repl)


def _norm_money(v: Any) -> str:
    s = _clean(v)
    if isinstance(v, (int, float)):
        s = f"{float(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return s.replace(' ', '')


def _iter_budget_items(nodes: Any, path: str = "orcamento_sintetico.itens_raiz") -> Iterable[Tuple[str, Dict[str, Any]]]:
    if not isinstance(nodes, list):
        return
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        cur = f"{path}.{i}"
        if str(node.get("tipo") or "").lower() == "item" or node.get("codigo"):
            key = f"budget::{node.get('item') or node.get('codigo') or cur}"
            yield key, node
        yield from _iter_budget_items(node.get("filhos"), cur + ".filhos")


def _iter_comp_rows(composicoes: Dict[str, Any] | None) -> Iterable[Tuple[str, Dict[str, Any]]]:
    comp = composicoes if isinstance(composicoes, dict) else {}
    for family in ("sinapi_like", "sicro"):
        fam = comp.get(family) if isinstance(comp.get(family), dict) else {}
        for collection in ("principais", "auxiliares_globais"):
            blocks = fam.get(collection) if isinstance(fam, dict) else None
            if not isinstance(blocks, dict):
                continue
            for block_key, block in blocks.items():
                if not isinstance(block, dict):
                    continue
                principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
                if principal:
                    yield f"{family}.{collection}.{block_key}.principal", principal
                for group in ("composicoes_auxiliares", "insumos"):
                    rows = block.get(group)
                    if isinstance(rows, list):
                        for idx, row in enumerate(rows):
                            if isinstance(row, dict):
                                yield f"{family}.{collection}.{block_key}.{group}.{idx}", row


def flatten_records(result: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    result = result or {}
    out: Dict[str, Dict[str, Any]] = {}
    for key, item in _iter_budget_items(((result.get("orcamento_sintetico") or {}).get("itens_raiz") or [])):
        out[key] = item
    for key, row in _iter_comp_rows(result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}):
        out[key] = row
    return out


def _field_equal(field: str, actual: Any, expected: Any) -> bool:
    if field in {"quant", "valor_unit", "total", "custo_parcial", "custo_total", "custo_unitario_sem_bdi", "custo_unitario_com_bdi", "preco_unitario", "custo_horario", "salario_hora"}:
        return _norm_money(actual) == _norm_money(expected)
    return _norm(actual) == _norm(expected)


def compute_field_accuracy(actual: Dict[str, Any], expected: Dict[str, Any], *, fields: List[str] | None = None) -> Dict[str, Any]:
    fields = fields or ["codigo", "banco", "fonte", "descricao", "especificacao", "und", "quant", "valor_unit", "total", "custo_parcial", "custo_total"]
    actual_records = flatten_records(actual)
    expected_records = flatten_records(expected)
    totals = {f: {"correct": 0, "total": 0, "missing": 0, "mismatches": []} for f in fields}
    record_correct = 0
    for rec_key, exp in expected_records.items():
        act = actual_records.get(rec_key)
        if act is None:
            for f in fields:
                if exp.get(f) not in (None, ""):
                    totals[f]["total"] += 1; totals[f]["missing"] += 1
            continue
        all_ok = True
        for f in fields:
            if exp.get(f) in (None, ""):
                continue
            totals[f]["total"] += 1
            ok = _field_equal(f, act.get(f), exp.get(f))
            if ok:
                totals[f]["correct"] += 1
            else:
                all_ok = False
                if len(totals[f]["mismatches"]) < 20:
                    totals[f]["mismatches"].append({"record": rec_key, "actual": act.get(f), "expected": exp.get(f)})
        if all_ok:
            record_correct += 1
    field_scores = {}
    correct_sum = total_sum = 0
    for f, data in totals.items():
        total = int(data["total"])
        correct = int(data["correct"])
        correct_sum += correct; total_sum += total
        field_scores[f] = {**data, "accuracy": round(correct / total, 4) if total else None}
    return {
        "version": VERSION,
        "record_count_expected": len(expected_records),
        "record_count_actual": len(actual_records),
        "record_exact_accuracy": round(record_correct / len(expected_records), 4) if expected_records else None,
        "overall_field_accuracy": round(correct_sum / total_sum, 4) if total_sum else None,
        "field_scores": field_scores,
    }


def generate_accuracy_report(version: str, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    case_reports = []
    weighted_correct = weighted_total = 0
    for case in cases:
        report = compute_field_accuracy(case.get("actual") or {}, case.get("expected") or {}, fields=case.get("fields"))
        name = case.get("name") or f"case_{len(case_reports)+1}"
        report["name"] = name
        case_reports.append(report)
        for fdata in report.get("field_scores", {}).values():
            weighted_correct += int(fdata.get("correct") or 0)
            weighted_total += int(fdata.get("total") or 0)
    return {
        "version": version or VERSION,
        "metric_version": VERSION,
        "case_count": len(case_reports),
        "overall_field_accuracy": round(weighted_correct / weighted_total, 4) if weighted_total else None,
        "cases": case_reports,
        "usefulness": "Compara campo a campo orçamento/composições contra golden esperado; adequado para relatório de acurácia por versão.",
    }


def report_to_markdown(report: Dict[str, Any]) -> str:
    lines = [f"# Relatório de acurácia — {report.get('version')}", "", f"Acurácia geral por campo: **{report.get('overall_field_accuracy')}**", "", "| Caso | Acurácia geral | Registros esperados |", "|---|---:|---:|"]
    for case in report.get("cases") or []:
        lines.append(f"| {case.get('name')} | {case.get('overall_field_accuracy')} | {case.get('record_count_expected')} |")
    return "\n".join(lines)
