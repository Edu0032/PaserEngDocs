from __future__ import annotations

from app.parser.candidate_profile_consensus_engine import (
    run_candidate_profile_consensus_engine,
    _subtract_neighbor_fragments,
)


def _budget_result(target_text: str):
    return {
        "orcamento_sintetico": {
            "itens_raiz": [
                {
                    "tipo": "meta",
                    "item": "3",
                    "descricao": "ESTACIONAMENTO",
                    "filhos": [
                        {
                            "tipo": "submeta",
                            "item": "3.2",
                            "descricao": "PAVIMENTAÇÃO",
                            "filhos": [
                                {
                                    "tipo": "item",
                                    "item": "3.2.6",
                                    "codigo": "96388",
                                    "fonte": "SINAPI",
                                    "especificacao": "CONSTRUÇÃO DE BASE E SUB-BASE PARA PAVIMENTAÇÃO DE SOLO DE COMPORTAMENTO LATERÍTICO - EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024",
                                },
                                {
                                    "tipo": "item",
                                    "item": "3.2.7",
                                    "codigo": "ANP 01",
                                    "fonte": "PRÓPRIO",
                                    "especificacao": target_text,
                                },
                                {
                                    "tipo": "item",
                                    "item": "3.2.8",
                                    "codigo": "96401",
                                    "fonte": "SINAPI",
                                    "especificacao": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - APENAS EXECUÇÃO",
                                },
                            ],
                        }
                    ],
                }
            ]
        },
        "composicoes": {"sinapi_like": {"principais": {}, "auxiliares_globais": {}}},
    }


def test_neighbor_subtraction_extracts_clean_target_from_polluted_current():
    current = "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024 AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -"
    context = {
        "prev": {"descricao": "CONSTRUÇÃO DE BASE E SUB-BASE - EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024"},
        "next": {"descricao": "EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - APENAS EXECUÇÃO"},
    }
    sub = _subtract_neighbor_fragments(current, context)
    assert sub["accepted"] is True
    assert sub["candidate"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"


def test_consensus_engine_reverse_repairs_anp01_with_neighbor_profiles():
    polluted = "- EXCLUSIVE ESCAVAÇÃO, CARGA E TRANSPORTE E SOLO. AF_09/2024 AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 -"
    result, report = run_candidate_profile_consensus_engine(_budget_result(polluted), apply=True)
    target = result["orcamento_sintetico"]["itens_raiz"][0]["filhos"][0]["filhos"][1]
    assert target["especificacao"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"
    assert report["summary"]["applied"] == 1
    assert report["applied"][0]["best"]["origin"] == "neighbor_subtraction"


def test_consensus_engine_keeps_clean_short_description():
    result, report = run_candidate_profile_consensus_engine(_budget_result("AQUISIÇÃO DE ASFALTO DILUIDO CM-30"), apply=True)
    target = result["orcamento_sintetico"]["itens_raiz"][0]["filhos"][0]["filhos"][1]
    assert target["especificacao"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"
    assert report["summary"]["applied"] == 0


def test_consensus_rejects_candidate_with_neighbor_description():
    # If current is already clean, the presence of a larger neighbour-owned text
    # in the registry must not replace it.
    data = _budget_result("AQUISIÇÃO DE ASFALTO DILUIDO CM-30")
    data["composicoes"]["sinapi_like"]["principais"] = {
        "ANP 01|PRÓPRIO": {
            "principal": {
                "codigo": "ANP 01",
                "banco": "PRÓPRIO",
                "descricao": "AQUISIÇÃO DE ASFALTO DILUIDO CM-30 EXECUÇÃO DE IMPRIMAÇÃO COM ASFALTO DILUÍDO CM-30. AF_11/2019 - APENAS EXECUÇÃO",
            }
        }
    }
    result, report = run_candidate_profile_consensus_engine(data, apply=True)
    target = result["orcamento_sintetico"]["itens_raiz"][0]["filhos"][0]["filhos"][1]
    assert target["especificacao"] == "AQUISIÇÃO DE ASFALTO DILUIDO CM-30"
    assert report["summary"]["applied"] == 0
