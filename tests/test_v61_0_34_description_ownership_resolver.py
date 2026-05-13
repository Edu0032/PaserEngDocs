from app.parser.description_ownership_resolver import (
    ownership_report,
    choose_clean_subcandidate_from_current,
    looks_complete_by_cell_occupancy,
)
from app.parser.selective_field_reparse_executor import run_selective_field_reparse_executor
from app.normalizer.field_recovery import _choose_best_candidate


def _anp_result_with_polluted_budget():
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {"tipo": "item", "item": "3.2.6", "codigo": "96388", "fonte": "SINAPI", "especificacao": "CONSTRUÇÃO DE BASE E SUB-BASE PARA PAVIMENTAÇÃO DE SOLO DE COMPORTAMENTO LATERÍTICO (ARENOSO), COM ESPESSURA DE 15 CM - EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024"},
                {"tipo": "item", "item": "3.2.7", "codigo": "ANP 01", "fonte": "PRÓPRIO", "especificacao": "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024 AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -"},
                {"tipo": "item", "item": "3.2.8", "codigo": "96401", "fonte": "SINAPI", "especificacao": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - APENAS EXECUÇÃO"},
            ]
        },
        "composicoes": {
            "sinapi_like": {
                "principais": {
                    "96388|SINAPI": {"principal": {"codigo": "96388", "banco": "SINAPI", "descricao": "CONSTRUÇÃO DE BASE E SUB-BASE PARA PAVIMENTAÇÃO DE SOLO DE COMPORTAMENTO LATERÍTICO (ARENOSO), COM ESPESSURA DE 15 CM - EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024"}},
                    "ANP01|PRÓPRIO": {"principal": {"codigo": "ANP 01", "banco": "PRÓPRIO", "descricao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"}},
                    "96401|SINAPI": {"principal": {"codigo": "96401", "banco": "SINAPI", "descricao": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - APENAS EXECUÇÃO"}},
                },
                "auxiliares_globais": {},
            }
        },
    }


def test_ownership_report_detects_candidate_owned_by_neighbor_rows():
    ctx = {
        "prev": {"codigo": "96388", "banco": "SINAPI", "confirmed_description": "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024"},
        "next": {"codigo": "96401", "banco": "SINAPI", "confirmed_description": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -"},
    }
    report = ownership_report("- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024 AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -", current_value="AQUISIÇÃO DE ASFALTO DILUIDO CM-30", neighbor_context=ctx)
    assert report["has_neighbor_hit"] is True
    assert {h["role"] for h in report["neighbor_hits"]} == {"prev", "next"}


def test_reverse_repair_uses_clean_same_code_candidate_inside_polluted_current():
    ctx = {
        "prev": {"confirmed_description": "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024"},
        "next": {"confirmed_description": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -"},
    }
    decision = choose_clean_subcandidate_from_current("- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024 AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -", "AQUISIÇÃO DE ASFALTO DILUIDO CM-30", ctx)
    assert decision["accepted"] is True
    assert decision["candidate"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"


def test_selective_field_executor_repairs_polluted_budget_using_composition_and_neighbors():
    patched, report = run_selective_field_reparse_executor(_anp_result_with_polluted_budget(), apply=True)
    item = patched["orcamento_sintetico"]["itens_raiz"][1]
    assert item["especificacao"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"
    assert any(p["codigo"] == "ANP 01" and p["decision"] == "accepted" for p in report["applied"])
    assert report["applied"][0].get("ownership") is not None


def test_recovery_candidate_selector_uses_neighbor_ownership_and_cell_occupancy():
    target = {
        "current_value": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30",
        "issue": "possible_broken_line_budget_description",
        "_recovery_current_occupancy": 0.33,
        "neighbor_context": {
            "prev": {"confirmed_description": "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024"},
            "next": {"confirmed_description": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -"},
        },
    }
    candidates = [
        {"value": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30", "strategy": "target_line_only", "fragments": []},
        {"value": "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024 AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -", "strategy": "upward_target_downward_fragments", "fragments": [{"direction": "up"}, {"direction": "down"}]},
    ]
    best = _choose_best_candidate(target, candidates, {})
    assert best["strategy"] == "target_line_only"
    assert best["safety_lock"] == "description_cell_occupancy_indicates_complete_short_text"
    assert looks_complete_by_cell_occupancy("AQUISIÇÃO DE ASFALTO DILUIDO CM-30", 0.33)
