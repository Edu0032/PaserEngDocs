from __future__ import annotations

"""Stable output schema helpers for Lovable (v61.0.57).

This module does not change the domain data.  It adds a predictable envelope
metadata contract to each public output and builds a package manifest so Lovable
can consume outputs without hunting for moving paths.
"""

from typing import Any, Dict, List

VERSION = "v61.0.75-correction-output-contract-and-review-index"
SCHEMA_VERSION = "outputs.v1"

DOCUMENTS = {
    "final_result": {
        "path": "root",
        "purpose": "dados limpos para popular o sistema; deve evitar diagnóstico pesado no caminho principal",
    },
    "correction_document": {
        "path": "documento_correcao",
        "purpose": "pendências acionáveis, revisão humana, suspeitas de erro humano/documental e ações para Lovable",
    },
    "evidence_document": {
        "path": "documento_evidencias",
        "purpose": "provas técnicas de como campos foram confirmados, corrigidos ou rejeitados",
    },
    "enrichment_document": {
        "path": "documento_enriquecimento",
        "purpose": "sugestões de enriquecimento do base_config/admin após aprovação humana",
    },
    "analytics_document": {
        "path": "analise_orcamentaria",
        "purpose": "métricas, acurácia, cobertura, confiança por entidade e contrato dos outputs",
    },
}


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _get_path(root: Dict[str, Any], dotted: str) -> Any:
    if dotted == "root":
        return root
    cur: Any = root
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_doc_metadata(doc: Dict[str, Any], *, document_type: str, purpose: str) -> None:
    doc.setdefault("schema_version", SCHEMA_VERSION)
    doc.setdefault("document_type", document_type)
    doc.setdefault("parser_version", VERSION)
    doc.setdefault("version", VERSION)
    doc.setdefault("purpose", purpose)


def build_outputs_package_manifest(final_result: Dict[str, Any]) -> Dict[str, Any]:
    docs: List[Dict[str, Any]] = []
    for doc_type, meta in DOCUMENTS.items():
        obj = _get_path(final_result, str(meta["path"]))
        docs.append({
            "document_type": doc_type,
            "path": meta["path"],
            "available": isinstance(obj, dict),
            "schema_version": _as_dict(obj).get("schema_version") if isinstance(obj, dict) else None,
            "purpose": meta["purpose"],
        })
    return {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "document_type": "outputs_package_manifest",
        "download_recommendation": "Lovable deve salvar/baixar cada documento separadamente ou como pacote completo de outputs.",
        "documents": docs,
        "canonical_names": {
            "final_result": "final_result.json",
            "correction_document": "correction_document.json",
            "evidence_document": "evidence_document.json",
            "enrichment_document": "enrichment_document.json",
            "analytics_document": "analytics_document.json",
        },
    }


def build_lovable_operational_summary(final_result: Dict[str, Any]) -> Dict[str, Any]:
    corr = _as_dict(final_result.get("documento_correcao"))
    painel = _as_dict(corr.get("painel_lovable"))
    human = _as_dict(corr.get("auditoria_humana"))
    hsum = _as_dict(human.get("summary"))
    analysis = _as_dict(final_result.get("analise_orcamentaria"))
    acc = _as_dict(analysis.get("accuracy_report"))
    accs = _as_dict(acc.get("summary"))
    cov = _as_dict(analysis.get("extraction_coverage_report"))
    covs = _as_dict(cov.get("summary"))
    sicro = _as_dict(cov.get("sicro"))
    qgate = _as_dict(_as_dict(final_result.get("auditoria_final")).get("quality_gate"))
    bloqueantes = int(hsum.get("bloqueantes") or _as_dict(_as_dict(painel.get("qualidade_final"))).get("bloqueantes") or 0)
    status_uso = "utilizavel" if bloqueantes == 0 and qgate.get("ok") is not False else "precisa_revisao"
    return {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "status_uso": status_uso,
        "mensagem": "JSON utilizável; revisar avisos/revisões não bloqueantes" if status_uso == "utilizavel" else "há pendência bloqueante antes do uso final",
        "bloqueantes": bloqueantes,
        "revisoes_recomendadas": int(hsum.get("revisoes_recomendadas") or 0),
        "avisos": int(hsum.get("avisos") or 0),
        "quality_gate_ok": qgate.get("ok"),
        "orcamento": {
            "itens": _as_dict(acc.get("budget")).get("leaf_items") or covs.get("budget_json_leaf_items"),
            "math_ok_rate": accs.get("budget_math_ok_rate"),
            "required_field_rate": accs.get("budget_required_field_rate"),
            "coverage_rate": _as_dict(cov.get("budget")).get("coverage_rate"),
        },
        "composicoes": {
            "principais": _as_dict(acc.get("compositions")).get("sinapi_like_principals") or covs.get("composition_principals"),
            "required_field_rate": accs.get("composition_principal_required_field_rate"),
            "triplet_ok_rate": accs.get("composition_principal_triplet_ok_rate"),
            "component_sum_ok_rate": accs.get("composition_component_sum_ok_rate"),
            "coverage_rate": _as_dict(cov.get("sinapi_like_compositions")).get("coverage_rate"),
        },
        "sicro": {
            "budget_sicro_items": sicro.get("budget_sicro_items"),
            "referenced_by_budget": sicro.get("referenced_by_budget"),
            "main_with_item_not_referenced_by_budget": sicro.get("main_with_item_not_referenced_by_budget"),
            "status": sicro.get("status"),
            "policy": sicro.get("rule"),
        },
    }


def normalize_output_schema_documents(final_result: Dict[str, Any]) -> Dict[str, Any]:
    final = final_result if isinstance(final_result, dict) else {}
    # Public companion docs.
    for doc_type, meta in DOCUMENTS.items():
        if doc_type == "final_result":
            continue
        obj = _get_path(final, str(meta["path"]))
        if isinstance(obj, dict):
            _set_doc_metadata(obj, document_type=doc_type if doc_type != "correction_document" else "documento_correcao", purpose=str(meta["purpose"]))

    analysis = final.setdefault("analise_orcamentaria", {})
    if isinstance(analysis, dict):
        _set_doc_metadata(analysis, document_type="analytics_document", purpose=DOCUMENTS["analytics_document"]["purpose"])
        manifest = build_outputs_package_manifest(final)
        analysis["outputs_package_manifest"] = manifest
        analysis["output_schema_stability"] = {
            "version": VERSION,
            "schema_version": SCHEMA_VERSION,
            "status": "ok",
            "principle": "cada output tem papel próprio, schema estável e caminho canônico para Lovable",
            "public_outputs": manifest["documents"],
            "role_separation": {
                "final_result": "resultado limpo",
                "documento_correcao": "revisões/problemas/ações humanas",
                "documento_evidencias": "provas técnicas",
                "documento_enriquecimento": "sugestões para base_config/admin",
                "analise_orcamentaria": "métricas e painéis",
            },
        }
        analysis["lovable_operational_summary"] = build_lovable_operational_summary(final)
        try:
            from app.pipeline.stage_registry import build_lovable_contract_reference
            analysis["lovable_contract_reference"] = build_lovable_contract_reference()
        except Exception as _contract_exc:  # pragma: no cover - defensive in Pyodide
            analysis.setdefault("lovable_contract_reference", {
                "version": VERSION,
                "schema_version": "lovable_contracts.v1",
                "status": "unavailable",
                "error": str(_contract_exc),
            })

    corr = _as_dict(final.get("documento_correcao"))
    if corr:
        corr["outputs_package_manifest"] = _as_dict(analysis.get("outputs_package_manifest"))
        corr["decisao_uso_lovable"] = _as_dict(analysis.get("lovable_operational_summary"))
        corr.setdefault("diagnosticos_internos", {})
        # Move only compact pointers here; keep heavy internals in evidence/analytics.
        corr["diagnosticos_internos"].setdefault("policy", "diagnósticos pesados ficam em documento_evidencias/analise_orcamentaria; Lovable deve priorizar auditoria_humana e painel_lovable")
    return final
