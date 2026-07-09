from __future__ import annotations

"""Line Certainty Closure Engine (v61.0.42).

This pass aligns the existing correction engines around a stricter goal: close
rows, not merely patch isolated fields.  It uses facts from the first extraction,
cross-table budget/composition agreement, auxiliary-global references, math
constraints and the native SICRO-only audit bridge.  When a row closes, its confirmed text is
registered in the ownership pool so it cannot be reused by neighbouring or
ambiguous rows.
"""

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Tuple

from app.parser.broken_line_recovery import codebank, is_truncated_text, pollution_reason, similarity
from app.parser.code_value_classifier import clean_text, norm_text
from app.parser.deep_area_sweep_recovery import build_deep_area_sweep_targets
from app.parser.extracted_evidence_cross_resolver import build_extracted_cross_candidates, build_report as build_extracted_cross_report
from app.parser.field_patch_validators import validate_patch_candidate
from app.parser.code_occurrence_sweep import build_full_pdf_code_bank_occurrence_targets
from app.parser.sicro_collection_enforcer import enforce_sicro_principal_auxiliary_collections
from app.parser.field_evidence_grade import field_grade_record, is_public_field_supported
from app.parser.final_reconciliation_pass import run_final_reconciliation
from app.parser.document_evidence_index import build_document_evidence_index, compact_index_report
from app.parser.field_consensus_engine import build_field_consensus_candidates
from app.parser.ownership_aware_field_consensus import enrich_consensus_with_ownership
from app.parser.budget_puzzle_resolver import build_budget_puzzle_context, compact_budget_puzzle_context
from app.parser.final_json_chain_organizer import organize_chain_analysis
from app.parser.adaptive_closure_scheduler import build_adaptive_closure_schedule
from app.parser.batch_code_bank_occurrence_indexer import build_batch_code_bank_occurrence_targets
from app.parser.runtime_evidence_cache import RuntimeEvidenceCache
from app.parser.physical_evidence_index import merge_physical_evidence_into_document_index, compact_physical_index_report
from app.parser.pipeline_consolidation import build_pipeline_consolidation_report, consolidate_correction_document
from app.parser.local_line_cascade_repair import build_local_line_cascade_candidates
from app.parser.output_documents_organizer import organize_lovable_output_documents
from app.core.output_compact import refresh_quality_gate_after_repairs
from app.parser.composition_principal_cascade_repair import apply_composition_principal_cascade_repair
from app.parser.field_evidence_ledger import FieldEvidenceLedger
from app.parser.fragment_ownership_pool import FragmentOwnershipPool
from app.parser.numeric_constraint_solver import (
    math_triplet_status,
    parse_ptbr_number,
    build_triplet_expectations,
)

VERSION = "v61.0.75-correction-output-contract-and-review-index"

DESCRIPTION_FIELDS = {"descricao", "especificacao"}
TEXT_FIELDS = {"descricao", "especificacao", "und", "codigo", "banco", "fonte"}
CONNECTOR_TAILS = {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O", "AO"}

SICRO_REQUIRED_BY_SECTION: Dict[str, List[str]] = {}  # v61.0.42: native sicro_only engine owns A-F contracts.


def _clean(v: Any) -> str:
    return clean_text(v)


def _empty(v: Any) -> bool:
    return v in (None, "")


def _looks_bad_text(value: Any) -> str:
    text = _clean(value)
    if not text:
        return "empty"
    if text.lstrip().startswith("-"):
        return "leading_orphan_fragment"
    if "=>" in text:
        return "arrow_marker"
    reason = pollution_reason(text)
    if reason:
        return str(reason)
    if norm_text(text).count("AF_") >= 2:
        return "multiple_service_anchors"
    return ""


def _weak_description(value: Any) -> str:
    reason = _looks_bad_text(value)
    if reason:
        return reason
    text = _clean(value)
    if is_truncated_text(text):
        return "truncated"
    tail = (norm_text(text).split() or [""])[-1]
    if tail in CONNECTOR_TAILS:
        return "ends_with_connector"
    return ""


def _get_path(root: Dict[str, Any], path: List[Any]) -> Any:
    cur: Any = root
    for p in path:
        try:
            if isinstance(cur, list):
                cur = cur[int(p)]
            elif isinstance(cur, dict):
                cur = cur[p]
            else:
                return None
        except Exception:
            return None
    return cur


def _set_path(root: Dict[str, Any], path: List[Any], value: Any) -> bool:
    if not path:
        return False
    parent = _get_path(root, path[:-1])
    key = path[-1]
    try:
        if isinstance(parent, list):
            parent[int(key)] = value
            return True
        if isinstance(parent, dict):
            parent[key] = value
            return True
    except Exception:
        return False
    return False


@dataclass
class ClosureRow:
    row_id: str
    family: str
    collection: str
    group: str
    path: List[Any]
    row: Dict[str, Any]
    field_name: str
    codigo: str = ""
    banco: str = ""
    item: str = ""
    page: int | None = None
    principal_key: str = ""
    row_index: int | None = None
    sicro_section: str = ""

    @property
    def key(self) -> str:
        return codebank(self.codigo, self.banco)

    @property
    def description(self) -> str:
        return _clean(self.row.get(self.field_name) or self.row.get("descricao") or self.row.get("especificacao") or "")


def _iter_budget_rows(result: Dict[str, Any]) -> Iterable[ClosureRow]:
    def walk(nodes: Any, base: List[Any]) -> Iterable[ClosureRow]:
        if not isinstance(nodes, list):
            return
        for idx, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            path = base + [idx]
            is_leaf = bool(node.get("codigo")) or str(node.get("tipo") or "").lower() == "item"
            if is_leaf:
                row_id = f"budget:{node.get('item') or '.'.join(map(str, path))}:{codebank(node.get('codigo'), node.get('fonte') or node.get('banco'))}"
                yield ClosureRow(
                    row_id=row_id,
                    family="budget",
                    collection="itens_raiz",
                    group="item",
                    path=path,
                    row=node,
                    field_name="especificacao" if "especificacao" in node else "descricao",
                    codigo=_clean(node.get("codigo")),
                    banco=_clean(node.get("fonte") or node.get("banco")),
                    item=_clean(node.get("item")),
                    page=node.get("pagina_inicio") or node.get("page_hint"),
                )
            yield from walk(node.get("filhos") or [], path + ["filhos"])
    yield from walk(((result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])


def _family_sources(composicoes: Dict[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    if not isinstance(composicoes, dict):
        return
    if isinstance(composicoes.get("sinapi_like"), dict) or isinstance(composicoes.get("sicro"), dict):
        for family in ("sinapi_like", "sicro"):
            fam = composicoes.get(family) or {}
            if not isinstance(fam, dict):
                continue
            for collection in ("principais", "auxiliares_globais"):
                blocks = fam.get(collection) or {}
                if isinstance(blocks, dict):
                    yield family, collection, blocks
    else:
        for collection in ("principais", "auxiliares_globais"):
            blocks = composicoes.get(collection) or {}
            if isinstance(blocks, dict):
                yield "legacy", collection, blocks


def _is_sicro_block(family: str, key: str, block: Dict[str, Any]) -> bool:
    if family == "sicro":
        return True
    if "|SICRO" in str(key).upper():
        return True
    principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
    bank = str(principal.get("banco") or principal.get("banco_coluna") or "").upper()
    return "SICRO" in bank or isinstance(block.get("sicro"), dict) or isinstance((block.get("detalhes") or {}).get("sicro"), dict)


def _iter_composition_rows(result: Dict[str, Any]) -> Iterable[ClosureRow]:
    comp = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    for family, collection, blocks in _family_sources(comp) or []:
        for key, block in (blocks or {}).items():
            if not isinstance(block, dict):
                continue
            fam = "sicro" if _is_sicro_block(family, str(key), block) else "sinapi_like"
            principal = block.get("principal") if isinstance(block.get("principal"), dict) else {}
            if principal:
                yield ClosureRow(
                    row_id=f"{fam}:{collection}:{key}:principal",
                    family=fam,
                    collection=collection,
                    group="principal",
                    path=["composicoes", family, collection, key, "principal"] if family in {"sinapi_like", "sicro"} else ["composicoes", collection, key, "principal"],
                    row=principal,
                    field_name="descricao",
                    codigo=_clean(principal.get("codigo") or (str(key).split("|", 1)[0] if "|" in str(key) else "")),
                    banco=_clean(principal.get("banco") or principal.get("fonte") or (str(key).split("|", 1)[1] if "|" in str(key) else "")),
                    item=_clean(block.get("item")),
                    page=principal.get("page_hint") or block.get("pagina_inicio"),
                    principal_key=str(key),
                )
            if fam == "sinapi_like":
                for group in ("composicoes_auxiliares", "insumos"):
                    rows = block.get(group) if isinstance(block.get(group), list) else []
                    for idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            continue
                        yield ClosureRow(
                            row_id=f"{fam}:{collection}:{key}:{group}:{idx}",
                            family=fam,
                            collection=collection,
                            group=group,
                            path=["composicoes", family, collection, key, group, idx] if family in {"sinapi_like", "sicro"} else ["composicoes", collection, key, group, idx],
                            row=row,
                            field_name="descricao",
                            codigo=_clean(row.get("codigo")),
                            banco=_clean(row.get("banco") or row.get("fonte")),
                            item=_clean(block.get("item")),
                            page=row.get("page_hint") or block.get("pagina_inicio"),
                            principal_key=str(key),
                            row_index=idx,
                        )
            else:
                # SICRO sections are validated under the block, not converted to
                # SINAPI-like rows.  Still expose section rows as closure rows so
                # correction_document can report them without generic validation.
                sicro = block.get("sicro") if isinstance(block.get("sicro"), dict) else (block.get("detalhes") or {}).get("sicro") if isinstance(block.get("detalhes"), dict) else {}
                secoes = sicro.get("secoes") if isinstance(sicro, dict) and isinstance(sicro.get("secoes"), dict) else {}
                for sec, sec_data in (secoes or {}).items():
                    rows = sec_data.get("linhas") if isinstance(sec_data, dict) else sec_data
                    if not isinstance(rows, list):
                        continue
                    for idx, row in enumerate(rows):
                        if not isinstance(row, dict):
                            continue
                        desc_field = next((f for f in ("descricao", "equipamento", "mao_obra", "material", "atividade_auxiliar", "tempo_fixo", "momento_transporte") if row.get(f)), "descricao")
                        yield ClosureRow(
                            row_id=f"sicro:{collection}:{key}:section:{sec}:{idx}",
                            family="sicro",
                            collection=collection,
                            group="section_row",
                            path=["composicoes", family, collection, key, "sicro", "secoes", sec, "linhas", idx] if family in {"sinapi_like", "sicro"} else ["composicoes", collection, key, "detalhes", "sicro", "secoes", sec, "linhas", idx],
                            row=row,
                            field_name=desc_field,
                            codigo=_clean(row.get("codigo") or row.get("insumo")),
                            banco=_clean(row.get("banco")),
                            item=_clean(block.get("item")),
                            page=block.get("pagina_inicio"),
                            principal_key=str(key),
                            row_index=idx,
                            sicro_section=str(sec),
                        )


def _collect_rows(result: Dict[str, Any]) -> List[ClosureRow]:
    return list(_iter_budget_rows(result)) + list(_iter_composition_rows(result))


def _register_evidence(rows: List[ClosureRow], ledger: FieldEvidenceLedger) -> None:
    for r in rows:
        source = f"{r.family}.{r.collection}.{r.group}"
        if r.description:
            ledger.add(r.codigo, r.banco, "descricao", r.description, source=source, path=r.path + [r.field_name])
            if r.family == "budget":
                ledger.add(r.codigo, r.banco, "especificacao", r.description, source=source, path=r.path + [r.field_name])
        for field in ("und", "quant", "valor_unit", "total", "custo_unitario_com_bdi", "custo_unitario_sem_bdi", "custo_parcial"):
            if r.row.get(field) not in (None, ""):
                ledger.add(r.codigo, r.banco, field, r.row.get(field), source=source, path=r.path + [field], confidence=0.88)


def _public_value_from_counterpart(row: ClosureRow, field: str, ledger: FieldEvidenceLedger) -> Any:
    key = row.key
    if not key:
        return None
    candidates: List[str]
    if field in {"descricao", "especificacao"}:
        candidates = ["descricao", "especificacao"]
    elif field == "und":
        candidates = ["und"]
    elif row.family == "budget" and field == "custo_unitario_com_bdi":
        candidates = ["valor_unit", "total", "custo_unitario_com_bdi"]
    elif row.family == "sinapi_like" and field in {"valor_unit", "total"}:
        candidates = ["custo_unitario_com_bdi", "valor_unit", "total"]
    else:
        candidates = [field]
    min_conf = 0.60 if field in {"descricao", "especificacao"} else 0.72
    for f in candidates:
        ev = ledger.best(key, f, min_confidence=min_conf)
        if ev and ev.value:
            return ev.value
    return None


def _safe_set_field(result: Dict[str, Any], row: ClosureRow, field: str, value: Any, repairs: List[Dict[str, Any]], *, reason: str, evidence: Dict[str, Any] | None = None) -> bool:
    if value in (None, ""):
        return False
    current = row.row.get(field)
    if not _empty(current):
        return False
    validation = validate_patch_candidate(field, value, row.row, evidence or {})
    if not validation.get("ok"):
        return False
    normalized = validation.get("normalized", value)
    if field in DESCRIPTION_FIELDS and _looks_bad_text(normalized):
        return False
    if _set_path(result, row.path + [field], normalized):
        row.row[field] = normalized
        repairs.append({"path": row.path + [field], "row_id": row.row_id, "family": row.family, "field": field, "before": current, "after": normalized, "reason": reason, "evidence": evidence or {}, "validation": validation})
        return True
    return False


def _safe_replace_description(result: Dict[str, Any], row: ClosureRow, value: Any, repairs: List[Dict[str, Any]], *, reason: str, evidence: Dict[str, Any] | None = None) -> bool:
    field = row.field_name
    current = row.row.get(field)
    cand = _clean(value)
    if not cand or _looks_bad_text(cand):
        return False
    if current and norm_text(current) == norm_text(cand):
        return False
    current_reason = _weak_description(current)
    if current and not current_reason:
        return False
    # Accept shorter replacement only when current is polluted and contains the
    # clean candidate.  This reverses earlier over-concatenation without letting
    # short aliases destroy valid long services.
    if current and len(cand) < len(_clean(current)):
        if norm_text(cand) not in norm_text(current) and similarity(cand, current) < 0.74:
            return False
    if _set_path(result, row.path + [field], cand):
        row.row[field] = cand
        repairs.append({"path": row.path + [field], "row_id": row.row_id, "family": row.family, "field": field, "before": current, "after": cand, "reason": reason, "evidence": evidence or {}})
        return True
    return False


def _apply_cross_table_repairs(result: Dict[str, Any], rows: List[ClosureRow], ledger: FieldEvidenceLedger) -> List[Dict[str, Any]]:
    """Mandatory light cross-resolution over already extracted facts.

    This is intentionally separate from any PDF scanning.  It runs every closure
    round and uses only the JSON/ledger already produced by previous extraction
    stages.  Quantities are never copied across budget/composition/global-aux
    contexts.
    """
    repairs: List[Dict[str, Any]] = []
    candidates = build_extracted_cross_candidates(rows, ledger, context={"base_config": {}})
    row_by_id = {r.row_id: r for r in rows}
    for cand in candidates:
        r = row_by_id.get(str(cand.get("row_id") or ""))
        if not r:
            continue
        field = str(cand.get("field") or "")
        value = cand.get("value")
        if field in DESCRIPTION_FIELDS or field == r.field_name:
            if _weak_description(r.row.get(r.field_name)):
                _safe_replace_description(result, r, value, repairs, reason="extracted_evidence_cross_resolution", evidence=cand)
        else:
            _safe_set_field(result, r, field, value, repairs, reason="extracted_evidence_cross_resolution", evidence=cand)
    return repairs



def _apply_field_consensus_repairs(result: Dict[str, Any], rows: List[ClosureRow], consensus_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply safe patches selected by the Document Evidence Index consensus.

    This sits between light extracted cross-resolution and heavy/local PDF sweeps.
    It can only write values that were present in extracted/indexed evidence, not
    math-only expectations.  Quantities remain protected by field_consensus_engine.
    """
    repairs: List[Dict[str, Any]] = []
    row_by_id = {r.row_id: r for r in rows}
    for cand in list((consensus_report or {}).get("candidates") or []):
        if not isinstance(cand, dict):
            continue
        r = row_by_id.get(str(cand.get("row_id") or ""))
        if not r:
            continue
        field = str(cand.get("field") or "")
        value = cand.get("value")
        reason = "field_consensus_resolution" if str(cand.get("source") or "") == "field_consensus_engine" else str(cand.get("reason") or "field_consensus_resolution")
        if field in DESCRIPTION_FIELDS or field == r.field_name:
            if _weak_description(r.row.get(r.field_name)):
                _safe_replace_description(result, r, value, repairs, reason=reason, evidence=cand)
        else:
            _safe_set_field(result, r, field, value, repairs, reason=reason, evidence=cand)
    return repairs

def _record_numeric_expectations(result: Dict[str, Any], rows: List[ClosureRow]) -> List[Dict[str, Any]]:
    """Store math-only expectations under _calc, never in public fields.

    The expected value is used by Deep Area Sweep / Full PDF Sweep to search for
    the same token in the physical row or nearby candidates.  It is not evidence
    by itself and therefore cannot close a public field alone.
    """
    expectations: List[Dict[str, Any]] = []
    for r in rows:
        items: List[Dict[str, Any]] = []
        if r.family == "budget":
            items.extend(build_triplet_expectations(r.row, quantity_field="quant", unit_field="custo_unitario_com_bdi", total_field="custo_parcial", rule_prefix="budget_math"))
        elif r.family == "sinapi_like" and r.group in {"principal", "composicoes_auxiliares", "insumos"}:
            items.extend(build_triplet_expectations(r.row, quantity_field="quant", unit_field="valor_unit", total_field="total", rule_prefix="composition_math"))
        if not items:
            continue
        calc = dict(r.row.get("_calc") or {})
        calc.setdefault("math_only_expectations", [])
        for item in items:
            item = {"row_id": r.row_id, "family": r.family, "path": r.path + [item.get("field")], **item}
            calc["math_only_expectations"].append(item)
            expectations.append(item)
        if _set_path(result, r.path + ["_calc"], calc):
            r.row["_calc"] = calc
    return expectations


def _field_missing_for_row(r: ClosureRow) -> List[str]:
    if r.family == "budget":
        req = ["codigo", "fonte", r.field_name, "und", "quant", "custo_unitario_com_bdi", "custo_parcial"]
    elif r.family == "sinapi_like":
        req = ["codigo", "banco", "descricao", "und", "quant", "valor_unit", "total"]
    elif r.family == "sicro" and r.group == "section_row":
        # v61.0.42: do not duplicate native sicro_only A-F contracts here.
        # The main closure only reports native SICRO audit/enforcer issues.
        req = []
    else:
        req = ["codigo", "banco", "descricao"]
    missing: List[str] = []
    for field in req:
        val = r.row.get(field)
        if _empty(val) or (field in DESCRIPTION_FIELDS and _looks_bad_text(val)):
            missing.append(field)
    return list(dict.fromkeys(missing))


def _math_status_for_row(r: ClosureRow) -> Dict[str, Any]:
    if r.family == "budget":
        return math_triplet_status(r.row, quantity_field="quant", unit_field="custo_unitario_com_bdi", total_field="custo_parcial")
    if r.family == "sinapi_like" and r.group in {"principal", "composicoes_auxiliares", "insumos"}:
        return math_triplet_status(r.row, quantity_field="quant", unit_field="valor_unit", total_field="total")
    return {"status": "not_applicable", "ok": True}


def _sicro_block_issue_rows(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    comp = result.get("composicoes") if isinstance(result.get("composicoes"), dict) else {}
    for family, collection, blocks in _family_sources(comp) or []:
        for key, block in (blocks or {}).items():
            if not isinstance(block, dict) or not _is_sicro_block(family, str(key), block):
                continue
            item = _clean(block.get("item"))
            if collection == "principais" and not item:
                issues.append({"code": "sicro_principal_without_item", "block": key, "collection": collection})
            if collection == "auxiliares_globais" and item:
                issues.append({"code": "sicro_auxiliar_with_item", "block": key, "collection": collection, "item": item})
            sicro = block.get("sicro") if isinstance(block.get("sicro"), dict) else (block.get("detalhes") or {}).get("sicro") if isinstance(block.get("detalhes"), dict) else {}
            validacao = sicro.get("validacao") if isinstance(sicro, dict) and isinstance(sicro.get("validacao"), dict) else {}
            for field in ("issues", "contract_issues", "text_warnings"):
                for issue in validacao.get(field) or []:
                    issues.append({"code": f"sicro_{field}", "block": key, "collection": collection, "issue": issue})
    return issues


def _status_for_row(r: ClosureRow, pool: FragmentOwnershipPool) -> Dict[str, Any]:
    if r.family == "sicro" and r.group == "section_row":
        return {
            "row_id": r.row_id,
            "family": r.family,
            "collection": r.collection,
            "group": r.group,
            "path": r.path,
            "codigo": r.codigo,
            "banco": r.banco,
            "item": r.item,
            "page": r.page,
            "field": r.field_name,
            "current_value": r.row.get(r.field_name),
            "missing_fields": [],
            "math_status": {"status": "not_applicable", "ok": True},
            "foreign_fragment_hits": [],
            "row_status": "closed_with_warning",
            "reasons": ["native_sicro_only_engine_authoritative_section_row_diagnostic"],
            "sicro_section": r.sicro_section or None,
            "field_evidence_grades": {},
        }
    missing = _field_missing_for_row(r)
    math_status = _math_status_for_row(r)
    desc_reason = _looks_bad_text(r.description) if r.description else "empty"
    foreign_hits = pool.foreign_hits(r.description, r.row_id) if r.description else []
    row_status = "closed_100"
    reasons: List[str] = []
    if missing:
        row_status = "unresolved"
        reasons.append("missing_or_polluted_fields")
    if math_status.get("ok") is False and math_status.get("status") != "not_applicable":
        row_status = "closed_with_warning" if row_status == "closed_100" else row_status
        reasons.append("math_not_closed")
    if desc_reason and desc_reason != "empty":
        row_status = "unresolved"
        reasons.append(f"description_issue:{desc_reason}")
    if foreign_hits:
        # A same codigo/banco description may legitimately appear in both budget
        # and composition.  Treat foreign ownership as a warning unless there are
        # missing/polluted fields; do not send good rows into recovery noise.
        row_status = "closed_with_warning" if row_status == "closed_100" else row_status
        reasons.append("description_contains_foreign_owned_fragment")
    if row_status == "closed_100" and r.description:
        pool.register(r.row_id, r.field_name, r.description, confidence=0.97, path=r.path + [r.field_name])
    fields_for_grade = []
    if r.family == "budget":
        fields_for_grade = ["codigo", "fonte", r.field_name, "und", "quant", "custo_unitario_com_bdi", "custo_parcial"]
    elif r.family == "sinapi_like":
        fields_for_grade = ["codigo", "banco", "descricao", "und", "quant", "valor_unit", "total"]
    elif r.family == "sicro" and r.group == "section_row":
        fields_for_grade = [f for f in ["codigo", "banco", r.field_name] if f]
    grades = {f: field_grade_record(f, r.row.get(f), evidence={"source": "existing_extraction_or_cross", "row_id": r.row_id}, math_status=math_status) for f in fields_for_grade}
    for exp in ((r.row.get("_calc") or {}).get("math_only_expectations") or []):
        if isinstance(exp, dict) and exp.get("field") in grades and _empty(r.row.get(exp.get("field"))):
            grades[exp.get("field")].update({"evidence_grade": "math_only_expected", "public_supported": False, "expected_value": exp.get("expected_value")})
    return {
        "row_id": r.row_id,
        "family": r.family,
        "collection": r.collection,
        "group": r.group,
        "path": r.path,
        "codigo": r.codigo,
        "banco": r.banco,
        "item": r.item,
        "page": r.page,
        "field": r.field_name,
        "current_value": r.row.get(r.field_name),
        "missing_fields": missing,
        "math_status": math_status,
        "foreign_fragment_hits": foreign_hits,
        "row_status": row_status,
        "reasons": reasons,
        "sicro_section": r.sicro_section or None,
        "field_evidence_grades": grades,
    }



def _active_rows_for_scheduler(rows: List[ClosureRow]) -> List[ClosureRow]:
    """Return rows that deserve active/expensive closure work this round.

    v61.0.42 makes the scheduler operational: rows already coherent do not
    consume field-consensus/deep evidence cycles.  P0/P1/P2 rows continue to
    receive consensus and physical-index candidates.
    """
    active: List[ClosureRow] = []
    for r in rows:
        if r.family == "sicro" and r.group == "section_row":
            continue
        missing = _field_missing_for_row(r)
        math_status = _math_status_for_row(r)
        desc_issue = _weak_description(r.description) if r.description else "empty"
        if missing or math_status.get("ok") is False or (desc_issue and desc_issue != "empty"):
            active.append(r)
    return active

def _sync_correction_document(result: Dict[str, Any], report: Dict[str, Any]) -> None:
    doc = result.setdefault("documento_correcao", {})
    if not isinstance(doc, dict):
        result["documento_correcao"] = doc = {}
    doc["line_certainty_closure"] = report
    doc["extracted_evidence_cross_resolver"] = report.get("extracted_evidence_cross_resolver") or {}
    doc["document_evidence_index"] = report.get("document_evidence_index") or {}
    doc["physical_evidence_index"] = report.get("physical_evidence_index") or {}
    doc["field_consensus_engine"] = report.get("field_consensus_engine") or {}
    doc["local_line_cascade_repair"] = report.get("local_line_cascade_repair") or {}
    doc["composition_principal_cascade_repair"] = report.get("composition_principal_cascade_repair") or {}
    doc["adaptive_closure_scheduler"] = report.get("adaptive_closure_scheduler") or {}
    doc["budget_puzzle_resolver"] = report.get("budget_puzzle_resolver") or {}
    _puzzle = report.get("budget_puzzle_resolver") or {}
    doc["budget_reconstruction_graph"] = _puzzle.get("budget_reconstruction_graph") or {}
    doc["composition_cost_reconciliation"] = _puzzle.get("composition_cost_reconciliation") or {}
    doc["budget_hierarchy_reconciliation"] = _puzzle.get("budget_hierarchy_reconciliation") or {}
    doc["entity_chain_conflict_resolver"] = _puzzle.get("entity_chain_conflict_resolver") or {}
    doc["strict_but_realistic_closure"] = (_puzzle.get("strict_but_realistic_closure") or {})
    doc["fragment_ownership_graph"] = ((report.get("budget_puzzle_resolver") or {}).get("fragment_ownership_graph") or {})
    doc["sicro_native_audit_bridge"] = report.get("sicro_native_audit_bridge") or {}
    doc["full_pdf_code_bank_occurrence_sweep"] = {
        "version": VERSION,
        "mode": "mandatory_global_code_bank_occurrence_targets_with_consensus",
        "target_count": len(report.get("full_pdf_code_bank_occurrence_targets") or []),
        "batch_target_count": len(report.get("full_pdf_code_bank_occurrence_batch_targets") or []),
        "targets": (report.get("full_pdf_code_bank_occurrence_targets") or [])[:80],
        "batch_targets": (report.get("full_pdf_code_bank_occurrence_batch_targets") or [])[:80],
    }
    warnings = doc.setdefault("warnings", [])
    if not isinstance(warnings, list):
        doc["warnings"] = warnings = []
    existing = {repr(w) for w in warnings}
    for row in report.get("rows") or []:
        if not isinstance(row, dict) or row.get("row_status") == "closed_100":
            continue
        entry = {
            "tipo": "line_certainty_unclosed",
            "row_id": row.get("row_id"),
            "family": row.get("family"),
            "codigo": row.get("codigo"),
            "banco": row.get("banco"),
            "item": row.get("item"),
            "missing_fields": row.get("missing_fields"),
            "reasons": row.get("reasons"),
            "math_status": row.get("math_status"),
        }
        marker = repr(entry)
        if marker not in existing:
            warnings.append(entry); existing.add(marker)
    for issue in report.get("sicro_issues") or []:
        entry = {"tipo": "sicro_closure_issue", **issue}
        marker = repr(entry)
        if marker not in existing:
            warnings.append(entry); existing.add(marker)
    for issue in (((report.get("budget_puzzle_resolver") or {}).get("budget_reconstruction_graph") or {}).get("missing_global_auxiliaries") or []):
        entry = {"tipo": "contextual_auxiliary_without_global_expansion", **issue}
        marker = repr(entry)
        if marker not in existing:
            warnings.append(entry); existing.add(marker)
    for conflict in (((report.get("budget_puzzle_resolver") or {}).get("entity_chain_conflict_resolver") or {}).get("conflicts") or []):
        entry = {"tipo": "entity_chain_conflict", **conflict}
        marker = repr(entry)
        if marker not in existing:
            warnings.append(entry); existing.add(marker)
    for repair in ((report.get("extracted_evidence_cross_resolver") or {}).get("applied") or []):
        entry = {
            "tipo": "extracted_cross_resolution",
            "row_id": repair.get("row_id"),
            "family": repair.get("family"),
            "field": repair.get("field"),
            "value": repair.get("after"),
            "reason": repair.get("reason"),
            "status": "applied",
        }
        marker = repr(entry)
        if marker not in existing:
            warnings.append(entry); existing.add(marker)
    resumo = doc.setdefault("resumo", {})
    if isinstance(resumo, dict):
        summary = report.get("summary") or {}
        resumo["line_certainty_total_rows"] = summary.get("total_rows")
        resumo["line_certainty_closed_100"] = summary.get("closed_100")
        resumo["line_certainty_unresolved"] = summary.get("unresolved")
        resumo["line_certainty_sicro_issues"] = len(report.get("sicro_issues") or [])
        resumo["budget_puzzle_entities"] = ((report.get("budget_puzzle_resolver") or {}).get("summary") or {}).get("entities")
        resumo["budget_puzzle_relations"] = ((report.get("budget_puzzle_resolver") or {}).get("summary") or {}).get("relations")
        _bp_summary = ((report.get("budget_puzzle_resolver") or {}).get("summary") or {})
        resumo["budget_puzzle_locked_fragments"] = _bp_summary.get("locked_fragments")
        resumo["budget_reconstruction_chains"] = _bp_summary.get("chains")
        resumo["budget_reconstruction_missing_global_auxiliaries"] = _bp_summary.get("missing_global_auxiliaries")
        resumo["composition_cost_mismatches"] = _bp_summary.get("composition_cost_mismatches")
        resumo["budget_hierarchy_mismatches"] = _bp_summary.get("budget_hierarchy_mismatches")
        resumo["entity_chain_conflicts"] = _bp_summary.get("chain_conflicts")
        if int(summary.get("unresolved") or 0) or report.get("sicro_issues"):
            resumo["total_registros_com_erro"] = max(int(resumo.get("total_registros_com_erro") or 0), 1)


def run_line_certainty_closure_engine(final_result: Dict[str, Any], *, apply: bool = True, max_rounds: int = 8) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    result = final_result if apply else copy.deepcopy(final_result)
    all_repairs: List[Dict[str, Any]] = []
    result, composition_cascade_initial_report = apply_composition_principal_cascade_repair(result)
    if (composition_cascade_initial_report.get("summary") or {}).get("fields_repaired"):
        all_repairs.extend([{**rep, "reason": "composition_principal_cascade_repair"} for rep in (composition_cascade_initial_report.get("repairs") or [])])
    result, sicro_enforcer_report = enforce_sicro_principal_auxiliary_collections(result, apply=True)
    round_reports: List[Dict[str, Any]] = []
    ledger = FieldEvidenceLedger()
    runtime_cache = RuntimeEvidenceCache()

    for round_idx in range(1, max(1, int(max_rounds)) + 1):
        rows = _collect_rows(result)
        ledger = FieldEvidenceLedger()
        _register_evidence(rows, ledger)
        cross_repairs = _apply_cross_table_repairs(result, rows, ledger)
        # Recollect after cross-table changes so numeric constraints see fresh values.
        rows = _collect_rows(result)
        math_expectations = _record_numeric_expectations(result, rows)
        # v61.0.41: build the document evidence index once per round and let a
        # field-level consensus layer close missing fields using already indexed
        # evidence.  This is still lighter and safer than physical PDF sweeps.
        physical_index = ((result.get("meta") or {}).get("performance") or {}).get("physical_evidence_index") or {}
        document_index = build_document_evidence_index(rows, ledger)
        document_index = merge_physical_evidence_into_document_index(document_index, physical_index)
        active_rows = _active_rows_for_scheduler(rows)
        consensus_report = build_field_consensus_candidates(active_rows, document_index, context={"base_config": {}})
        # v61.0.43: before applying consensus, view the budget as a puzzle of
        # related entities and owned physical fragments.  This can boost/select
        # candidates supported by the same codigo+banco entity cluster without
        # inventing values or copying contextual quantities.
        puzzle_round_context = build_budget_puzzle_context(result, physical_index, [])
        consensus_report = enrich_consensus_with_ownership(consensus_report, puzzle_round_context.get("fragment_ownership_graph") or {}, puzzle_round_context.get("entity_relation_graph") or {})
        cascade_report = build_local_line_cascade_candidates(active_rows, physical_index, document_index, context={"base_config": {}})
        cascade_report = enrich_consensus_with_ownership(cascade_report, puzzle_round_context.get("fragment_ownership_graph") or {}, puzzle_round_context.get("entity_relation_graph") or {})
        # v61.0.47: use the row-local cascade before the generic consensus so
        # the most contextual candidate gets first chance to close the field.
        cascade_repairs = _apply_field_consensus_repairs(result, rows, cascade_report)
        consensus_repairs = _apply_field_consensus_repairs(result, rows, consensus_report)
        round_repairs = cross_repairs + cascade_repairs + consensus_repairs
        all_repairs.extend(round_repairs)
        round_reports.append({"round": round_idx, "cross_repairs": len(cross_repairs), "field_consensus_repairs": len(consensus_repairs), "local_line_cascade_repairs": len(cascade_repairs), "field_consensus_candidates": consensus_report.get("candidate_count", 0), "local_line_cascade_candidates": cascade_report.get("candidate_count", 0), "active_scheduler_rows": len(active_rows), "physical_index_used": bool((physical_index or {}).get("key_count")), "math_expectations": len(math_expectations), "numeric_public_repairs": len([r for r in cascade_repairs if r.get("field") in {"quant", "valor_unit", "total", "custo_unitario_com_bdi", "custo_parcial"}]), "total_repairs": len(round_repairs)})
        if not round_repairs:
            break

    result, composition_cascade_final_report = apply_composition_principal_cascade_repair(result)
    if (composition_cascade_final_report.get('summary') or {}).get('fields_repaired'):
        all_repairs.extend([{**rep, 'reason': 'composition_principal_cascade_repair'} for rep in (composition_cascade_final_report.get('repairs') or [])])
    rows = _collect_rows(result)
    ledger = FieldEvidenceLedger()
    _register_evidence(rows, ledger)
    pool = FragmentOwnershipPool()
    row_reports: List[Dict[str, Any]] = []
    # First pass registers obvious closed descriptions, second pass checks all rows.
    preliminary: List[Tuple[ClosureRow, List[str], Dict[str, Any]]] = []
    for r in rows:
        missing = _field_missing_for_row(r)
        math_status = _math_status_for_row(r)
        if not missing and math_status.get("ok", True) and r.description and not _looks_bad_text(r.description):
            pool.register(r.row_id, r.field_name, r.description, confidence=0.97, path=r.path + [r.field_name])
        preliminary.append((r, missing, math_status))
    for r, _missing, _math_status in preliminary:
        row_reports.append(_status_for_row(r, pool))

    physical_index = ((result.get("meta") or {}).get("performance") or {}).get("physical_evidence_index") or {}
    document_index = build_document_evidence_index(rows, ledger, closure_rows=row_reports)
    document_index = merge_physical_evidence_into_document_index(document_index, physical_index)
    document_index = runtime_cache.set("document_evidence_index", document_index)
    document_index_report = compact_index_report(document_index)
    physical_index_report = compact_physical_index_report(physical_index) if isinstance(physical_index, dict) and physical_index else {"version": VERSION, "status": "not_built", "key_count": 0, "occurrence_count": 0}
    budget_puzzle_context = build_budget_puzzle_context(result, physical_index, row_reports)
    final_consensus_report = build_field_consensus_candidates(rows, document_index, context={"base_config": {}})
    final_consensus_report = enrich_consensus_with_ownership(final_consensus_report, budget_puzzle_context.get("fragment_ownership_graph") or {}, budget_puzzle_context.get("entity_relation_graph") or {})
    final_cascade_report = build_local_line_cascade_candidates(_active_rows_for_scheduler(rows), physical_index, document_index, context={"base_config": {}})
    final_cascade_report = enrich_consensus_with_ownership(final_cascade_report, budget_puzzle_context.get("fragment_ownership_graph") or {}, budget_puzzle_context.get("entity_relation_graph") or {})
    adaptive_schedule = build_adaptive_closure_schedule(row_reports)

    sicro_section_report = {"version": VERSION, "mode": "native_sicro_only_engine_is_authoritative", "status": "not_run_in_main_parser", "issues": []}
    sicro_issues = _sicro_block_issue_rows(result)
    summary = {
        "version": VERSION,
        "rounds": len(round_reports),
        "repairs_applied": len(all_repairs),
        "total_rows": len(row_reports),
        "closed_100": sum(1 for r in row_reports if r.get("row_status") == "closed_100"),
        "closed_with_warning": sum(1 for r in row_reports if r.get("row_status") == "closed_with_warning"),
        "unresolved": sum(1 for r in row_reports if r.get("row_status") == "unresolved"),
        "closed_by_strong_consensus": ((budget_puzzle_context.get("strict_but_realistic_closure") or {}).get("summary") or {}).get("closed_by_strong_consensus", 0),
        "puzzle_entities": (budget_puzzle_context.get("summary") or {}).get("entities", 0),
        "puzzle_relations": (budget_puzzle_context.get("summary") or {}).get("relations", 0),
        "puzzle_fragments": (budget_puzzle_context.get("summary") or {}).get("fragments", 0),
        "budget_reconstruction_chains": (budget_puzzle_context.get("summary") or {}).get("chains", 0),
        "composition_cost_mismatches": (budget_puzzle_context.get("summary") or {}).get("composition_cost_mismatches", 0),
        "budget_hierarchy_mismatches": (budget_puzzle_context.get("summary") or {}).get("budget_hierarchy_mismatches", 0),
        "entity_chain_conflicts": (budget_puzzle_context.get("summary") or {}).get("chain_conflicts", 0),
        "missing_global_auxiliaries": (budget_puzzle_context.get("summary") or {}).get("missing_global_auxiliaries", 0),
        "sicro_issues": len(sicro_issues),
    }
    extracted_repairs = [r for r in all_repairs if r.get("reason") == "extracted_evidence_cross_resolution"]
    report = {
        "version": VERSION,
        "summary": summary,
        "rounds": round_reports,
        "repairs": all_repairs[:500],
        "rows": row_reports[:1200],
        "sicro_issues": sicro_issues[:300],
        "evidence_ledger": ledger.as_dict(limit=120),
        "fragment_ownership_pool": pool.as_dict(limit=120),
        "extracted_evidence_cross_resolver": build_extracted_cross_report([], extracted_repairs),
        "sicro_collection_enforcer": sicro_enforcer_report,
        "sicro_native_audit_bridge": sicro_section_report,
        "physical_evidence_index": physical_index_report,
        "document_evidence_index": document_index_report,
        "field_consensus_engine": {"version": final_consensus_report.get("version"), "mode": final_consensus_report.get("mode"), "candidate_count": final_consensus_report.get("candidate_count"), "ownership_supported_candidates": final_consensus_report.get("ownership_supported_candidates", 0), "rejected_count": final_consensus_report.get("rejected_count"), "candidates": (final_consensus_report.get("candidates") or [])[:120], "rejected": (final_consensus_report.get("rejected") or [])[:120]},
        "local_line_cascade_repair": {"version": final_cascade_report.get("version"), "mode": final_cascade_report.get("mode"), "candidate_count": final_cascade_report.get("candidate_count"), "ownership_supported_candidates": final_cascade_report.get("ownership_supported_candidates", 0), "rejected_count": final_cascade_report.get("rejected_count"), "math_expected_searches": final_cascade_report.get("math_expected_searches"), "candidates": (final_cascade_report.get("candidates") or [])[:120], "rejected": (final_cascade_report.get("rejected") or [])[:120]},
        "adaptive_closure_scheduler": adaptive_schedule,
        "budget_puzzle_resolver": compact_budget_puzzle_context(budget_puzzle_context),
        "runtime_evidence_cache": runtime_cache.as_dict(),
        "composition_principal_cascade_repair": {
            "version": VERSION,
            "mode": "composition_principal_cascade_and_contextual_quantity_guard",
            "repairs": (composition_cascade_initial_report.get("repairs") or []) + (composition_cascade_final_report.get("repairs") if 'composition_cascade_final_report' in locals() else [] or []),
            "blocked": (composition_cascade_initial_report.get("blocked") or []) + (composition_cascade_final_report.get("blocked") if 'composition_cascade_final_report' in locals() else [] or []),
            "summary": {
                "repairs": len((composition_cascade_initial_report.get("repairs") or []) + (composition_cascade_final_report.get("repairs") if 'composition_cascade_final_report' in locals() else [] or [])),
                "fields_repaired": sum(len(r.get("repairs") or []) for r in ((composition_cascade_initial_report.get("repairs") or []) + (composition_cascade_final_report.get("repairs") if 'composition_cascade_final_report' in locals() else [] or []))),
                "blocked": len((composition_cascade_initial_report.get("blocked") or []) + (composition_cascade_final_report.get("blocked") if 'composition_cascade_final_report' in locals() else [] or [])),
            },
        },
    }
    report["deep_area_sweep_targets"] = build_deep_area_sweep_targets(report, max_targets=120)
    report["full_pdf_code_bank_occurrence_targets"] = build_full_pdf_code_bank_occurrence_targets(report, max_targets=60)
    report["full_pdf_code_bank_occurrence_batch_targets"] = build_batch_code_bank_occurrence_targets(report, max_keys=80)
    result.setdefault("meta", {}).setdefault("performance", {})["line_certainty_closure_engine"] = report
    organize_chain_analysis(result, budget_puzzle_context)
    final_reconciliation_report = run_final_reconciliation(result, report)
    report["final_reconciliation_pass"] = final_reconciliation_report
    report["pipeline_consolidation"] = build_pipeline_consolidation_report(result, report)
    _sync_correction_document(result, report)
    report["pipeline_consolidation"] = consolidate_correction_document(result, report)
    organize_lovable_output_documents(result, report)
    refresh_quality_gate_after_repairs(result)
    organize_lovable_output_documents(result, report)
    if summary["unresolved"] or summary["sicro_issues"]:
        result.setdefault("validacao", {}).setdefault("ocorrencias", []).append({
            "codigo": "line_certainty_closure_unresolved",
            "severidade": "aviso",
            "categoria": "validacao",
            "mensagem": f"Line Certainty Closure fechou {summary['closed_100']}/{summary['total_rows']} linhas com certeza; pendentes={summary['unresolved']}; sicro_issues={summary['sicro_issues']}.",
            "etapa": "line_certainty_closure_engine",
            "evidencia": summary,
        })
    else:
        result.setdefault("validacao", {}).setdefault("ocorrencias", []).append({
            "codigo": "line_certainty_closure_ok",
            "severidade": "info",
            "categoria": "validacao",
            "mensagem": f"Line Certainty Closure fechou todas as {summary['total_rows']} linhas avaliadas com evidência forte.",
            "etapa": "line_certainty_closure_engine",
            "evidencia": summary,
        })
    return result, report
