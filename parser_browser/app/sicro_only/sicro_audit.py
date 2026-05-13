from __future__ import annotations

from typing import Any, Dict, List


def audit_extraction_contract(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Strict structural audit for SICRO-only outputs.

    This is intentionally separate from mathematical validation. It checks the
    semantic contract Eduardo wants before integration into the monorepo:
    principal first, A-F lettered sections preserved, A/B without preco_unitario,
    C/D/E with preco_unitario, valid bank family and row-level validations.
    """
    issues: List[Dict[str, Any]] = []
    valid_banks = {"SICRO", "SICRO2", "SICRO3"}
    comps = result.get("composicoes") or {}
    for comp_key, comp in comps.items():
        principal = comp.get("principal") or {}
        if not principal.get("codigo") or not principal.get("banco") or not principal.get("servico"):
            issues.append({"composicao": comp_key, "tipo": "principal_incompleta"})
        if principal.get("banco") not in valid_banks:
            issues.append({"composicao": comp_key, "tipo": "banco_principal_invalido", "valor": principal.get("banco")})
        if not comp.get("secoes"):
            issues.append({"composicao": comp_key, "tipo": "sem_secoes"})
        for sec, section in (comp.get("secoes") or {}).items():
            rows = section.get("linhas") or []
            if sec not in "ABCDEF":
                issues.append({"composicao": comp_key, "tipo": "secao_invalida", "section": sec})
            for idx, row in enumerate(rows):
                bank = row.get("banco")
                if bank not in valid_banks:
                    issues.append({"composicao": comp_key, "tipo": "banco_linha_invalido", "section": sec, "idx": idx, "valor": bank})
                if sec in {"A", "B"} and "preco_unitario" in row:
                    issues.append({"composicao": comp_key, "tipo": "preco_unitario_nao_deveria_existir", "section": sec, "idx": idx})
                if sec in {"C", "D", "E"} and not row.get("preco_unitario"):
                    issues.append({"composicao": comp_key, "tipo": "preco_unitario_obrigatorio_ausente", "section": sec, "idx": idx})
                if sec in {"C", "D", "E", "F"} and not row.get("unidade"):
                    issues.append({"composicao": comp_key, "tipo": "unidade_ausente", "section": sec, "idx": idx})
                val = row.get("validacao") or {}
                if val and not val.get("ok", True):
                    issues.append({"composicao": comp_key, "tipo": "validacao_linha_falhou", "section": sec, "idx": idx, "mensagens": val.get("messages")})
                if not row.get("_evidence"):
                    issues.append({"composicao": comp_key, "tipo": "evidencia_ausente", "section": sec, "idx": idx})
        val = comp.get("validacao") or {}
        if not val.get("ok", True):
            issues.append({"composicao": comp_key, "tipo": "validacao_composicao_falhou", "issues": val.get("issues")})
    return issues
