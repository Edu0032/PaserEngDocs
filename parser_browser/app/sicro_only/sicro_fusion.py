from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import product
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .sicro_engine import SicroEngine, RowValidation, dec_to_ptbr, parse_decimal
from .sicro_profile import profile_confirms_field
from .sicro_quality import annotate_confidence


@dataclass
class FieldCandidate:
    composition: str
    section: str
    row_key: str
    field: str
    value: Any
    engine: str
    score: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "composition": self.composition,
            "section": self.section,
            "row_key": self.row_key,
            "field": self.field,
            "value": self.value,
            "engine": self.engine,
            "score": round(float(self.score), 3),
            "evidence": self.evidence,
            "reasons": self.reasons,
        }


class CandidatePool:
    def __init__(self, engine: SicroEngine | None = None):
        self.engine = engine or SicroEngine()
        self.candidates: List[FieldCandidate] = []

    @staticmethod
    def row_key(section: str, row: Dict[str, Any], idx: int) -> str:
        return f"{idx}:{row.get("codigo") or row.get("insumo") or "row"}"

    def add_result(self, result: Dict[str, Any], engine_name: str, production: bool = True) -> None:
        for comp_key, comp in (result.get("composicoes") or {}).items():
            for sec, section in (comp.get("secoes") or {}).items():
                for idx, row in enumerate(section.get("linhas") or []):
                    rk = self.row_key(sec, row, idx)
                    valid = (row.get("validacao") or {}).get("ok", True)
                    for field_name in ["codigo", "insumo", "banco", "unidade", "quantidade", "preco_unitario", "custo_horario", "salario_hora"]:
                        if field_name not in row or row.get(field_name) in (None, ""):
                            continue
                        conf = ((row.get("_confidence") or {}).get(field_name) or {}).get("score")
                        score = float(conf) if conf is not None else 0.55
                        if valid:
                            score += 0.15
                        if production:
                            score += 0.10
                        if row.get("_recovery"):
                            score -= 0.03
                        self.candidates.append(FieldCandidate(
                            composition=comp_key,
                            section=sec,
                            row_key=rk,
                            field=field_name,
                            value=row.get(field_name),
                            engine=engine_name,
                            score=max(0.0, min(1.25, score)),
                            evidence=(row.get("_field_evidence") or {}).get(field_name) or row.get("_evidence") or {},
                            reasons=["candidate_from_engine", "row_math_ok" if valid else "row_math_failed"],
                        ))

    def candidates_for(self, comp: str, sec: str, row_key: str, field: str) -> List[FieldCandidate]:
        return [c for c in self.candidates if c.composition == comp and c.section == sec and c.row_key == row_key and c.field == field]

    def as_report(self, limit: int = 400) -> Dict[str, Any]:
        return {
            "total_candidates": len(self.candidates),
            "sample": [c.as_dict() for c in sorted(self.candidates, key=lambda c: c.score, reverse=True)[:limit]],
        }


def _best_math_combo(engine: SicroEngine, section: str, candidates: Dict[str, List[FieldCandidate]]) -> Optional[Tuple[Dict[str, FieldCandidate], RowValidation, float]]:
    if section in {"C", "D", "E"}:
        qcs = candidates.get("quantidade") or []
        pcs = candidates.get("preco_unitario") or []
        ccs = candidates.get("custo_horario") or []
        formula = "quantidade * preco_unitario"
        best = None
        for q, p, c in product(qcs, pcs, ccs):
            qd = parse_decimal(q.value); pd = parse_decimal(p.value); cd = parse_decimal(c.value)
            if qd is None or pd is None or cd is None:
                continue
            val = engine._validate(formula, qd * pd, cd)
            if not val.ok:
                continue
            score = q.score + p.score + c.score + 0.7
            if best is None or score > best[2]:
                best = ({"quantidade": q, "preco_unitario": p, "custo_horario": c}, val, score)
        return best
    if section == "B":
        qcs = candidates.get("quantidade") or []
        scs = candidates.get("salario_hora") or []
        ccs = candidates.get("custo_horario") or []
        best = None
        for q, sal, c in product(qcs, scs, ccs):
            qd = parse_decimal(q.value); sd = parse_decimal(sal.value); cd = parse_decimal(c.value)
            if qd is None or sd is None or cd is None:
                continue
            val = engine._validate("quantidade * salario_hora", qd * sd, cd)
            if not val.ok:
                continue
            score = q.score + sal.score + c.score + 0.7
            if best is None or score > best[2]:
                best = ({"quantidade": q, "salario_hora": sal, "custo_horario": c}, val, score)
        return best
    return None


class SicroEvidenceFusionEngine:
    VERSION = "v61.0.20-sicro-evidence-layout-fusion"

    def __init__(self, engine: SicroEngine | None = None, profile: Dict[str, Any] | None = None):
        self.engine = engine or SicroEngine()
        self.profile = profile or {}

    def fuse(self, selected: Dict[str, Any], engine_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        base = deepcopy(selected)
        pool = CandidatePool(self.engine)
        for cand in engine_candidates:
            result = cand.get("result")
            if not result:
                continue
            profile_name = cand.get("profile", {}).get("name") or cand.get("score", {}).get("profile") or "unknown"
            production = bool(cand.get("profile", {}).get("production", True))
            pool.add_result(result, profile_name, production=production)
        repairs: List[Dict[str, Any]] = []
        discarded: List[Dict[str, Any]] = []
        for comp_key, comp in (base.get("composicoes") or {}).items():
            for sec, section in (comp.get("secoes") or {}).items():
                for idx, row in enumerate(section.get("linhas") or []):
                    rk = CandidatePool.row_key(sec, row, idx)
                    field_map = {f: pool.candidates_for(comp_key, sec, rk, f) for f in ["quantidade", "preco_unitario", "custo_horario", "salario_hora"]}
                    # Profile bonus: if a candidate has bbox compatible with the learned field band.
                    for f, cands in field_map.items():
                        for c in cands:
                            if profile_confirms_field(self.profile, sec, f, c.evidence):
                                c.score = min(1.35, c.score + 0.08)
                                c.reasons.append("learned_profile_confirms_section_band")
                    combo = _best_math_combo(self.engine, sec, field_map)
                    if combo:
                        chosen, validation, combo_score = combo
                        changed = False
                        original = {f: row.get(f) for f in chosen}
                        for f, cand in chosen.items():
                            if str(row.get(f)) != str(cand.value):
                                row[f] = cand.value
                                changed = True
                        if changed or not (row.get("validacao") or {}).get("ok", True):
                            row["validacao"] = validation.as_dict()
                            row.setdefault("_fusion", {})["math_combo"] = {
                                "applied": True,
                                "version": self.VERSION,
                                "original": original,
                                "chosen": {f: c.as_dict() for f, c in chosen.items()},
                                "combo_score": round(combo_score, 3),
                            }
                            repairs.append({"composition": comp_key, "section": sec, "row_key": rk, "strategy": "math_combo", "chosen": {f: c.value for f, c in chosen.items()}})
                        # Keep a short discard report for auditability.
                        for f, cands in field_map.items():
                            chosen_val = str(row.get(f))
                            for c in cands:
                                if str(c.value) != chosen_val:
                                    discarded.append({"composition": comp_key, "section": sec, "row_key": rk, "field": f, "value": c.value, "engine": c.engine, "score": round(c.score, 3)})
        # Recalculate metadata issue count after fusion.
        issues: List[Dict[str, Any]] = []
        for comp_key, comp in (base.get("composicoes") or {}).items():
            comp_issues = []
            for sec, section in (comp.get("secoes") or {}).items():
                for row in section.get("linhas") or []:
                    val = row.get("validacao") or {}
                    if val and not val.get("ok", True):
                        comp_issues.append({"tipo": "row_math", "section": sec, "codigo": row.get("codigo") or row.get("insumo"), **val})
            comp.setdefault("validacao", {})["issues_after_fusion"] = comp_issues
            if comp_issues:
                comp.setdefault("validacao", {})["ok"] = False
            for issue in comp_issues:
                issues.append({"composicao": comp_key, **issue})
        base["issues"] = issues
        base.setdefault("metadata", {})["total_issues"] = len(issues)
        base["fusion"] = {
            "version": self.VERSION,
            "enabled": True,
            "candidate_pool": pool.as_report(limit=120),
            "repairs": repairs,
            "discarded_candidates_sample": discarded[:120],
            "profile_used": self.profile,
            "selection_unit": "field/row/section/layout rather than whole-engine only",
            "layout_hardening": {"unknown_columns_allowed": True, "math_hypothesis_solver": True, "content_role_classifier": True, "browser_parity_ready": True, "stabilized_passes": True},
        }
        base = annotate_confidence(base, self.engine)
        return base
