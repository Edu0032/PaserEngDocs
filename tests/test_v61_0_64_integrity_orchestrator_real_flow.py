from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.browser.pyodide_entry import run_core_extraction_accuracy_flow_file_json, run_real_flow_mandatory_recovery_file_json
from app.config.version import CURRENT_RELEASE
from app.parser.integrity_orchestrator import run_final_integrity_orchestrator
from test_v61_0_62_composition_locking_budget_ownership import _result_with_blockers


def _write_problem_pages_pdf(path: Path) -> None:
    doc = fitz.open()
    for page_no in range(1, 31):
        page = doc.new_page(width=900, height=1200)
        text = f"Página {page_no}"
        if page_no == 24:
            text = """
 4.5.2 Código Banco Descrição Tipo Und Quant. Valor Unit Total
Composição 93391 SINAPI REVESTIMENTO CERÂMICO PARA PISO COM PLACAS TIPO ESMALTADA PADRÃO PISO - PISOS m² 1,0000000 69,88 69,88
Composição Auxiliar 88256 SINAPI AZULEJISTA OU LADRILHISTA COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,2411000 31,60 7,61
Composição Auxiliar 88316 SINAPI SERVENTE COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,1290000 24,36 3,14
Insumo 00001381 SINAPI ARGAMASSA COLANTE AC I PARA CERAMICAS Material KG 9,1325000 1,08 9,86
Insumo 00034357 SINAPI REJUNTE CIMENTICIO, QUALQUER COR Material KG 0,2410000 6,34 1,52
Insumo 00001297 SINAPI PISO EM CERAMICA ESMALTADA, COMERCIAL (PADRAO POPULAR), PEI MAIOR OU IGUAL Material m² 1,0571000 45,18 47,75
A 3, FORMATO MENOR OU IGUAL A 2025 CM2
MO sem LS 3,70 LS => 4,22MO com LS => 7,92
Valor do BDI 15,11 Valor com BDI => 84,99
 4.5.3 Código Banco Descrição Tipo Und Quant. Valor Unit Total
"""
        elif page_no == 29:
            text = """
 4.9.2 Código Banco Descrição Tipo Und Quant. Valor Unit Total
Composição 89446 SINAPI TUBO, PVC, SOLDÁVEL, DE 25MM, INSTALADO EM PRUMADA DE ÁGUA - FORNECIMENTO Instalações Prediais de M 1,0000000 5,47 5,47
E INSTALAÇÃO. AF_06/2022 Água Fria em PVC
Composição Auxiliar 88248 SINAPI AUXILIAR DE ENCANADOR OU BOMBEIRO HIDRÁULICO COM ENCARGOS Livro SINAPI: Cálculos e H 0,0195000 25,34 0,49
Composição Auxiliar 88267 SINAPI ENCANADOR OU BOMBEIRO HIDRÁULICO COM ENCARGOS COMPLEMENTARES Livro SINAPI: Cálculos e H 0,0195000 31,03 0,60
Insumo 00009868 SINAPI TUBO PVC, SOLDAVEL, DE 25 MM, AGUA FRIA (NBR-5648) Material M 1,0493000 4,17 4,37
Insumo 00038383 SINAPI LIXA D'AGUA EM FOLHA, COR PRETA, GRAO 100 Material UN 0,0045000 2,55 0,01
"""
        page.insert_text((40, 60), text, fontsize=9)
    doc.save(path)
    doc.close()


def _critical_assertions(out: dict) -> None:
    assert out["status"] == "ok"
    gate = out["auditoria_final"]["quality_gate"]
    assert gate["ok"] is True
    assert gate.get("blocking_issue_count", 0) == 0
    assert out["meta"]["parser_version"] == CURRENT_RELEASE
    assert out["documento_correcao"]["versao"] == CURRENT_RELEASE
    assert out["lovable_consumption_policy"]["do_not_recalculate_public_totals"] is True

    comps_root = out["composicoes"]
    comps = (comps_root.get("principais") or (comps_root.get("sinapi_like") or {}).get("principais"))
    row_1297 = [r for r in comps["93391|SINAPI"]["insumos"] if r.get("codigo") == "00001297"][0]
    assert row_1297["und"] == "m²"
    assert row_1297["quant"] == "1,0571000"
    assert row_1297["valor_unit"] == "45,18"
    assert row_1297["total"] == "47,75"
    math_93391 = comps["93391|SINAPI"]["detalhes"]["math_status"]
    assert math_93391["status"] == "ok"
    assert math_93391["missing_component_totals"] == 0
    assert round(float(math_93391["component_sum"]), 2) == 69.88

    principal_89446 = comps["89446|SINAPI"]["principal"]
    assert principal_89446["quant"] == "1,0000000"
    assert principal_89446["valor_unit"] == "5,47"
    assert principal_89446["total"] == "5,47"

    root = out["orcamento_sintetico"]["itens_raiz"][0]
    assert root["custo_total"] == "52.365,69"
    assert "custo_total" not in root["filhos"][0]


def test_v61_0_64_exported_output_contract_real_flow_runs_integrity_orchestrator(tmp_path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    options = {"accuracy_profile": {"enable_physical_evidence_index": False}}
    out = json.loads(run_core_extraction_accuracy_flow_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps(options)))
    _critical_assertions(out)
    perf = out["meta"]["performance"]
    assert "mandatory_real_flow_recovery_pre_output_contract" in perf or "final_integrity_orchestrator" in perf


def test_v61_0_64_worker_post_organizer_real_flow_runs_same_integrity_orchestrator(tmp_path):
    pdf_path = tmp_path / "critical-pages.pdf"
    _write_problem_pages_pdf(pdf_path)
    out = json.loads(run_real_flow_mandatory_recovery_file_json(str(pdf_path), json.dumps(_result_with_blockers()), json.dumps({})))
    _critical_assertions(out)
    assert "mandatory_real_flow_recovery_after_organizer" in out["meta"]["performance"]


def test_v61_0_64_mandatory_orchestrator_failure_blocks_ok(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr("app.parser.integrity_orchestrator.apply_budget_total_ownership_repair", fail)
    out, report = run_final_integrity_orchestrator(_result_with_blockers(), pdf_bytes=b"not a pdf", perf_key="forced_failure_test")
    assert out["status"] == "quality_gate_failed"
    gate = out["auditoria_final"]["quality_gate"]
    assert gate["ok"] is False
    assert any(i.get("code") == "mandatory_integrity_orchestrator_failed" for i in gate.get("issues", []))
    assert report["errors"]
