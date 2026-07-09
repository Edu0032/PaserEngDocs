from __future__ import annotations

from app.browser.recovery_agent import apply_recovery_patches, apply_targeted_recovery_to_final_result
from app.normalizer import field_recovery
from app.normalizer.field_recovery import recover_fields
from app.parser.code_occurrence_sweep import build_full_pdf_code_bank_occurrence_targets
from app.parser.field_patch_validators import validate_money_candidate, validate_quantity_candidate, validate_unit_candidate
from app.parser.line_certainty_closure import run_line_certainty_closure_engine


def _final_with_open_composition():
    return {
        "orcamento_sintetico": {"itens_raiz": []},
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "89446|SINAPI": {
                        "pagina_inicio": 29,
                        "principal": {
                            "codigo": "89446",
                            "banco": "SINAPI",
                            "descricao": "TUBO PVC",
                            "und": "m",
                            "quant": "1,0000000",
                            "valor_unit": "14,27",
                            "total": "",
                        },
                        "composicoes_auxiliares": [],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {},
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }


def test_field_validators_reject_codes_and_accept_units_numbers():
    assert validate_unit_candidate("m²")["ok"] is True
    assert validate_unit_candidate("74209/001")["ok"] is False
    assert validate_quantity_candidate("1,0000000")["ok"] is True
    assert validate_quantity_candidate("CP - 120")["ok"] is False
    assert validate_money_candidate("1.608,72")["ok"] is True
    assert validate_money_candidate("ANP 01")["ok"] is False


def test_recovery_commit_accepts_numeric_and_reclosure_removes_missing_total():
    final = _final_with_open_composition()
    recovery = {
        "attempted": True,
        "patches": [
            {
                "target_id": "closure::89446::total",
                "path": ["composicoes", "sinapi_like", "principais", "89446|SINAPI", "principal", "total"],
                "field": "total",
                "value": "14,27",
                "confidence": 0.96,
                "codigo": "89446",
                "banco": "SINAPI",
                "family": "sinapi_like",
                "collection": "principais",
                "row_group": "principal",
                "issue": "line_certainty_unclosed_field",
                "source": "deep_area_sweep_executor",
            }
        ],
        "unresolved": [],
    }
    out = apply_targeted_recovery_to_final_result(final, recovery, min_confidence=0.85)
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["total"] == "14,27"
    assert out["meta"]["targeted_recovery"]["committed"] == 1
    assert out["meta"]["targeted_recovery"]["line_certainty_reclosed_after_recovery"] is True
    rows = out["documento_correcao"]["line_certainty_closure"]["rows"]
    target = [r for r in rows if r["codigo"] == "89446" and r["group"] == "principal"][0]
    assert "total" not in target["missing_fields"]


def test_extracted_cross_resolver_is_mandatory_before_pdf_sweep_and_does_not_copy_quantities():
    final = {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "1.1", "codigo": "89446", "fonte": "SINAPI", "especificacao": "TUBO PVC", "und": "m", "quant": "25,00", "custo_unitario_com_bdi": "14,27", "custo_parcial": "356,75", "filhos": []}
            ]
        },
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "89446|SINAPI": {
                        "pagina_inicio": 29,
                        "principal": {"codigo": "89446", "banco": "SINAPI", "descricao": "", "und": "", "quant": "1,0000000", "valor_unit": "", "total": ""},
                        "composicoes_auxiliares": [],
                        "insumos": [],
                    }
                },
                "auxiliares_globais": {},
            },
            "sicro": {"principais": {}, "auxiliares_globais": {}},
        },
        "documento_correcao": {"resumo": {}},
        "validacao": {"ocorrencias": []},
        "meta": {"performance": {}},
    }
    out, report = run_line_certainty_closure_engine(final, apply=True)
    principal = out["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]
    assert principal["descricao"] == "TUBO PVC"
    assert principal["und"] == "m"
    assert principal["valor_unit"] == "14,27"
    assert principal["quant"] == "1,0000000"
    assert report["extracted_evidence_cross_resolver"]["applied_count"] >= 2
    assert out["documento_correcao"]["extracted_evidence_cross_resolver"]["mode"] == "already_extracted_evidence_only"


def test_full_pdf_code_bank_occurrence_targets_are_separate_late_fallback():
    final = _final_with_open_composition()
    final["composicoes"]["sinapi_like"]["principais"]["89446|SINAPI"]["principal"]["und"] = ""
    _out, report = run_line_certainty_closure_engine(final, apply=True)
    targets = build_full_pdf_code_bank_occurrence_targets(report)
    assert targets
    assert targets[0]["strategy"] == "full_pdf_code_bank_occurrence_sweep"
    assert targets[0]["priority"] == "late_fallback"


def test_deep_area_sweep_executor_recovers_numeric_field_from_column_band(monkeypatch):
    words = []
    for text, x0, x1 in [
        ("89446", 10, 40),
        ("SINAPI", 50, 85),
        ("TUBO", 100, 160),
        ("m", 210, 220),
        ("1,0000000", 260, 310),
        ("14,27", 350, 390),
        ("14,27", 430, 470),
    ]:
        words.append({"text": text, "x0": x0, "x1": x1, "y0": 100, "y1": 110})
    line = {"text": "89446 SINAPI TUBO m 1,0000000 14,27 14,27", "norm_text": "89446 SINAPI TUBO M 1,0000000 14,27 14,27", "words": words, "x0": 10, "x1": 470, "y0": 100, "y1": 110}
    monkeypatch.setattr(field_recovery, "extract_page_geometry", lambda _pdf: {1: {"lines": [line]}})
    payload = {
        "page_map": {"1": 29},
        "apply_confidence_min": 0.80,
        "column_maps": {
            "composition": {
                "columns": [
                    {"canonical": "codigo", "x0": 10, "x1": 45},
                    {"canonical": "banco", "x0": 50, "x1": 90},
                    {"canonical": "descricao", "x0": 100, "x1": 200},
                    {"canonical": "und", "x0": 205, "x1": 235},
                    {"canonical": "quant", "x0": 250, "x1": 320},
                    {"canonical": "valor_unit", "x0": 340, "x1": 400},
                    {"canonical": "total", "x0": 420, "x1": 480},
                ]
            }
        },
        "targets": [
            {
                "target_id": "closure::89446::valor_unit",
                "path": ["composicoes", "sinapi_like", "principais", "89446|SINAPI", "principal", "valor_unit"],
                "field": "valor_unit",
                "codigo": "89446",
                "banco": "SINAPI",
                "page": 29,
                "family": "sinapi_like",
                "row_snapshot": {"quant": "1,0000000", "total": "14,27"},
            }
        ],
    }
    result = recover_fields(b"fake", payload)
    assert result["patches"]
    assert result["patches"][0]["field"] == "valor_unit"
    assert result["patches"][0]["value"] == "14,27"
    assert result["patches"][0]["source"] == "deep_area_sweep_executor"


def test_workers_expose_iterative_reclosure_and_full_pdf_targets():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for worker in [root / "parser_browser/browser/pyodide/pyodide-parser-worker.js", root / "parser_browser/browser/demo/pyodide/pyodide-parser-worker.js"]:
        text = worker.read_text(encoding="utf-8")
        assert "addTargetsFromFullPdfCodeBankSweep" in text
        assert "full_pdf_code_bank_occurrence_target: true" in text
        assert "targeted-recovery-cycle-started" in text
        assert "max_targeted_recovery_cycles" in text
        assert "line_certainty_reclosed_after_recovery" in text
