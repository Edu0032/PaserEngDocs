from __future__ import annotations

"""Layout-hardening utilities for SICRO tables.

This module is intentionally Pyodide-safe: only stdlib, deterministic heuristics,
and no heavy numeric dependencies. It protects the extractor from documents where
SICRO sections have extra columns, shifted columns, reordered code/bank columns,
missing headers, or wrapped descriptions.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations, permutations
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .sicro_engine import SicroEngine, clean, key, normalize_code, parse_decimal


@dataclass
class ColumnRole:
    role: str
    confidence: float
    reasons: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class LayoutColumn:
    column_id: str
    x0: float
    x1: float
    values: List[str]
    header: str = ""
    role: str = "unknown"
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return (float(self.x0) + float(self.x1)) / 2.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "column_id": self.column_id,
            "x0": round(float(self.x0), 2),
            "x1": round(float(self.x1), 2),
            "header": self.header,
            "values": self.values,
            "role": self.role,
            "confidence": round(float(self.confidence), 3),
            "reasons": self.reasons,
        }


@dataclass
class LayoutSolveResult:
    ok: bool
    section: str
    row: Dict[str, Any]
    validation: Dict[str, Any]
    canonical_columns: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    unknown_columns: List[Dict[str, Any]] = field(default_factory=list)
    layout_confidence: Dict[str, Any] = field(default_factory=dict)
    hypotheses_tested: int = 0
    chosen_hypothesis: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "section": self.section,
            "row": self.row,
            "validation": self.validation,
            "canonical_columns": self.canonical_columns,
            "unknown_columns": self.unknown_columns,
            "layout_confidence": self.layout_confidence,
            "hypotheses_tested": self.hypotheses_tested,
            "chosen_hypothesis": self.chosen_hypothesis,
        }


class ColumnRoleClassifier:
    """Classify column roles from their content instead of positional index."""

    HEADER_ANCHORS: Dict[str, Tuple[str, ...]] = {
        "codigo": ("CODIGO", "CÓDIGO", "INSUMO"),
        "banco": ("BANCO", "FONTE"),
        "descricao": ("DESCRICAO", "DESCRIÇÃO", "EQUIPAMENT", "MAO DE OBRA", "MÃO DE OBRA", "MATERIAL", "ATIVIDADE", "TEMPO", "MOMENTO"),
        "unidade": ("UND", "UNIDADE"),
        "quantidade": ("QUANT", "QUANTIDADE", "COEF"),
        "preco_unitario": ("PRECO UNITARIO", "PREÇO UNITÁRIO", "PRECO", "PREÇO", "SALARIO", "SALÁRIO", "CUSTO OPERATIVO", "CUSTO IMPRODUTIVO"),
        "custo_horario": ("CUSTO HORARIO", "CUSTO HORÁRIO", "CUSTO HORARIO", "TOTAL", "CUSTO"),
    }

    def __init__(self, engine: SicroEngine | None = None):
        self.engine = engine or SicroEngine()

    def _is_known_unit(self, token: str, section: str) -> bool:
        raw_key = key(token).replace("²", "2").replace("³", "3")
        candidates: List[str] = []
        candidates.extend(self.engine.units.get("by_section", {}).get(section, []))
        candidates.extend(self.engine.units.get("common", []))
        normalized = {key(u).replace("²", "2").replace("³", "3") for u in candidates}
        return raw_key in normalized

    def _ratio(self, values: Sequence[str], predicate) -> float:
        vals = [clean(v) for v in values if clean(v)]
        if not vals:
            return 0.0
        return sum(1 for v in vals if predicate(v)) / len(vals)

    def _header_score(self, header: str, role: str) -> float:
        hk = key(str(header).replace("_", " ").replace("-", " "))
        if not hk:
            return 0.0
        return 1.0 if any(key(a) in hk for a in self.HEADER_ANCHORS.get(role, ())) else 0.0

    def score_column(self, section: str, col: LayoutColumn) -> Dict[str, float]:
        vals = [clean(v) for v in col.values if clean(v)]
        scores: Dict[str, float] = {}
        numeric_ratio = self._ratio(vals, lambda v: parse_decimal(v) is not None)
        bank_ratio = self._ratio(vals, self.engine.is_bank)
        code_ratio = self._ratio(vals, lambda v: bool(self.engine.classify_code(v)))
        unit_ratio = self._ratio(vals, lambda v: self._is_known_unit(v, section))
        text_ratio = self._ratio(vals, lambda v: parse_decimal(v) is None and not self.engine.is_bank(v) and not self.engine.classify_code(v))
        avg_len = (sum(len(v) for v in vals) / len(vals)) if vals else 0.0

        scores["banco"] = max(bank_ratio, self._header_score(col.header, "banco"))
        # Section-specific code scoring avoids treating every 7-digit number as price.
        if section == "A":
            scores["codigo"] = self._ratio(vals, lambda v: self.engine.classify_code(v) == "equipamento")
        elif section == "B":
            scores["codigo"] = self._ratio(vals, lambda v: self.engine.classify_code(v) == "mao_obra")
        elif section in {"C", "F"}:
            scores["codigo"] = self._ratio(vals, lambda v: self.engine.classify_code(v) == "material")
        elif section in {"D", "E"}:
            scores["codigo"] = code_ratio
        else:
            scores["codigo"] = code_ratio
        scores["codigo"] = max(scores["codigo"], self._header_score(col.header, "codigo") * 0.80)
        scores["unidade"] = max(unit_ratio, self._header_score(col.header, "unidade") * 0.90)
        scores["descricao"] = max(0.0, min(1.0, text_ratio * 0.75 + (0.25 if avg_len > 12 else 0.0) + self._header_score(col.header, "descricao") * 0.35))
        # Monetary/numeric roles are deliberately generic here; the hypothesis solver
        # assigns quantity/preco/custo through section math.
        scores["numeric"] = numeric_ratio
        scores["quantidade"] = max(numeric_ratio * 0.70, self._header_score(col.header, "quantidade") * 1.15)
        scores["preco_unitario"] = max(numeric_ratio * 0.70, self._header_score(col.header, "preco_unitario") * 1.15)
        scores["custo_horario"] = max(numeric_ratio * 0.70, self._header_score(col.header, "custo_horario") * 1.15)
        return scores

    def classify(self, section: str, columns: Sequence[Dict[str, Any] | LayoutColumn]) -> List[LayoutColumn]:
        out: List[LayoutColumn] = []
        for idx, raw in enumerate(columns):
            if isinstance(raw, LayoutColumn):
                col = raw
            else:
                col = LayoutColumn(
                    column_id=str(raw.get("column_id") or raw.get("id") or f"col_{idx}"),
                    x0=float(raw.get("x0", idx * 10.0)),
                    x1=float(raw.get("x1", idx * 10.0 + 8.0)),
                    values=[str(v) for v in raw.get("values", [])],
                    header=str(raw.get("header", "")),
                )
            scores = self.score_column(section, col)
            # Description can coexist with text columns; unknown wins if max evidence is weak.
            best_role, best_score = max(scores.items(), key=lambda kv: kv[1])
            if best_role == "numeric":
                best_role = "numeric_unknown"
            if best_score < 0.42:
                best_role = "unknown"
            col.role = best_role
            col.confidence = float(best_score)
            col.reasons = [f"{best_role}_score={best_score:.2f}"]
            out.append(col)
        # Avoid many duplicate canonical roles when an extra text/number column exists.
        return self._resolve_role_collisions(section, out)

    def _resolve_role_collisions(self, section: str, cols: List[LayoutColumn]) -> List[LayoutColumn]:
        unique_roles = {"codigo", "banco", "unidade"}
        for role in unique_roles:
            same = [c for c in cols if c.role == role]
            if len(same) <= 1:
                continue
            winner = max(same, key=lambda c: c.confidence)
            for c in same:
                if c is not winner:
                    c.role = "unknown"
                    c.reasons.append(f"downgraded_duplicate_{role}")
        return cols


class LayoutHypothesisSolver:
    """Build row hypotheses from content-classified columns and section math."""

    def __init__(self, engine: SicroEngine | None = None):
        self.engine = engine or SicroEngine()
        self.classifier = ColumnRoleClassifier(self.engine)

    def solve(self, section: str, columns: Sequence[Dict[str, Any] | LayoutColumn]) -> LayoutSolveResult:
        classified = self.classifier.classify(section, columns)
        if section in {"C", "D", "E"}:
            return self._solve_cde(section, classified)
        if section == "B":
            return self._solve_b(section, classified)
        if section == "A":
            return self._solve_a(section, classified)
        if section == "F":
            return self._solve_f(section, classified)
        return LayoutSolveResult(False, section, {}, {"ok": False, "messages": ["Unsupported section"]})

    def _is_known_unit(self, token: str, section: str) -> bool:
        raw_key = key(token).replace("²", "2").replace("³", "3")
        candidates: List[str] = []
        candidates.extend(self.engine.units.get("by_section", {}).get(section, []))
        candidates.extend(self.engine.units.get("common", []))
        normalized = {key(u).replace("²", "2").replace("³", "3") for u in candidates}
        return raw_key in normalized

    def _col_values(self, cols: Sequence[LayoutColumn], role: str) -> List[Tuple[LayoutColumn, str]]:
        out: List[Tuple[LayoutColumn, str]] = []
        for c in cols:
            if c.role == role or (role == "numeric" and c.role in {"numeric_unknown", "quantidade", "preco_unitario", "custo_horario"}):
                out.extend((c, v) for v in c.values if clean(v))
        return out

    def _all_tokens(self, cols: Sequence[LayoutColumn]) -> List[Tuple[LayoutColumn, str]]:
        return [(c, v) for c in cols for v in c.values if clean(v)]

    def _unknowns(self, cols: Sequence[LayoutColumn], used_cols: Iterable[str]) -> List[Dict[str, Any]]:
        used = set(used_cols)
        return [c.as_dict() for c in cols if c.column_id not in used and c.role in {"unknown", "numeric_unknown", "descricao"} and c.values]

    def _first_bank(self, cols: Sequence[LayoutColumn]) -> Tuple[Optional[LayoutColumn], str]:
        for c, v in self._all_tokens(cols):
            if self.engine.is_bank(v):
                return c, self.engine.normalize_bank(v)
        return None, ""

    def _first_code(self, cols: Sequence[LayoutColumn], section: str) -> Tuple[Optional[LayoutColumn], str]:
        expected = {"A": "equipamento", "B": "mao_obra", "C": "material", "F": "material"}.get(section)
        for c, v in self._all_tokens(cols):
            typ = self.engine.classify_code(v)
            if expected and typ == expected:
                return c, normalize_code(v)
            if section in {"D", "E"} and typ in {"composicao", "servico_auxiliar", "servico_tempo_fixo", "servico_transporte"}:
                return c, normalize_code(v)
        return None, ""

    def _unit_candidates(self, cols: Sequence[LayoutColumn], section: str) -> List[Tuple[LayoutColumn, str]]:
        return [(c, v) for c, v in self._all_tokens(cols) if self._is_known_unit(v, section) and parse_decimal(v) is None and not self.engine.is_bank(v) and not self.engine.classify_code(v)]

    def _num_candidates(self, cols: Sequence[LayoutColumn]) -> List[Tuple[LayoutColumn, str, Decimal]]:
        out: List[Tuple[LayoutColumn, str, Decimal]] = []
        for c, v in self._all_tokens(cols):
            d = parse_decimal(v)
            if d is not None:
                out.append((c, v, d))
        return out

    def _description(self, cols: Sequence[LayoutColumn], used_col_ids: Iterable[str], section: str) -> str:
        used = set(used_col_ids)
        desc_parts: List[Tuple[float, str]] = []
        for c, v in self._all_tokens(cols):
            if c.column_id in used:
                continue
            if parse_decimal(v) is not None or self.engine.is_bank(v) or self.engine.classify_code(v) or self.engine.is_unit(v, section):
                continue
            if key(v) in {"INSUMO", "COMPOSICAO", "COMPOSIÇÃO", "AUXILIAR", "ATIVIDADE", "TEMPO", "FIXO"}:
                continue
            desc_parts.append((c.cx, v))
        return clean(" ".join(v for _, v in sorted(desc_parts)))

    def _score_layout(self, cols: Sequence[LayoutColumn], validation_ok: bool, used_count: int) -> Dict[str, Any]:
        base = 0.35
        avg_conf = sum(c.confidence for c in cols) / len(cols) if cols else 0.0
        score = base + avg_conf * 0.35 + (0.25 if validation_ok else 0.0) + min(0.10, used_count * 0.01)
        return {
            "score": round(min(1.0, score), 3),
            "signals": ["content_role_classifier", "section_math_ok" if validation_ok else "section_math_failed", "unknown_columns_allowed"],
        }

    def _solve_cde(self, section: str, cols: List[LayoutColumn]) -> LayoutSolveResult:
        bank_col, bank = self._first_bank(cols)
        code_col, code = self._first_code(cols, section)
        unit_candidates = self._unit_candidates(cols, section)
        nums = self._num_candidates(cols)[-7:]
        best = None
        tested = 0
        for (unit_col, unit) in unit_candidates or [(None, "")]:
            for combo in combinations(nums, 3):
                for q, price, cost in permutations(combo, 3):
                    tested += 1
                    qcol, qtxt, qd = q
                    pcol, ptxt, pd = price
                    ccol, ctxt, cd = cost
                    val = self.engine._validate("quantidade * preco_unitario", qd * pd, cd)
                    if not val.ok:
                        continue
                    # Prefer the visual left-to-right q < price < cost when available, but allow reorder.
                    visual_bonus = 0.10 if qcol.cx <= pcol.cx <= ccol.cx else 0.02
                    role_bonus = sum([qcol.role == "quantidade", pcol.role == "preco_unitario", ccol.role == "custo_horario"]) * 0.60
                    score = qcol.confidence + pcol.confidence + ccol.confidence + visual_bonus + role_bonus
                    if best is None or score > best[0]:
                        best = (score, unit_col, unit, q, price, cost, val)
        if best is None or not bank or not code:
            msg = []
            if not bank: msg.append("bank_not_found")
            if not code: msg.append("code_not_found")
            if best is None: msg.append("math_combo_not_found")
            return LayoutSolveResult(False, section, {}, {"ok": False, "messages": msg}, hypotheses_tested=tested)
        _, unit_col, unit, q, price, cost, val = best
        qcol, qtxt, _ = q; pcol, ptxt, _ = price; ccol, ctxt, _ = cost
        used_cols = {c.column_id for c in [bank_col, code_col, unit_col, qcol, pcol, ccol] if c is not None}
        desc = self._description(cols, used_cols, section)
        row: Dict[str, Any] = {
            "banco": bank,
            "codigo": code,
            "quantidade": qtxt,
            "unidade": unit,
            "preco_unitario": ptxt,
            "custo_horario": ctxt,
        }
        if section == "C": row["material"] = desc
        elif section == "D": row["atividade_auxiliar"] = desc
        else: row["tempo_fixo"] = desc
        canonical = {
            "banco": bank_col.as_dict() if bank_col else {},
            "codigo": code_col.as_dict() if code_col else {},
            "unidade": unit_col.as_dict() if unit_col else {},
            "quantidade": qcol.as_dict(),
            "preco_unitario": pcol.as_dict(),
            "custo_horario": ccol.as_dict(),
        }
        return LayoutSolveResult(True, section, row, val.as_dict(), canonical, self._unknowns(cols, used_cols), self._score_layout(cols, val.ok, len(used_cols)), tested, {"strategy": "content_columns_math_combo", "q": qtxt, "preco": ptxt, "custo": ctxt})

    def _solve_b(self, section: str, cols: List[LayoutColumn]) -> LayoutSolveResult:
        bank_col, bank = self._first_bank(cols)
        code_col, code = self._first_code(cols, section)
        nums = self._num_candidates(cols)[-6:]
        best = None; tested = 0
        for combo in combinations(nums, 3):
            for q, sal, cost in permutations(combo, 3):
                tested += 1
                qcol, qtxt, qd = q; scol, stxt, sd = sal; ccol, ctxt, cd = cost
                val = self.engine._validate("quantidade * salario_hora", qd * sd, cd)
                if val.ok:
                    score = qcol.confidence + scol.confidence + ccol.confidence + sum([qcol.role == "quantidade", scol.role == "preco_unitario", ccol.role == "custo_horario"]) * 0.50 + (0.10 if qcol.cx <= scol.cx <= ccol.cx else 0.02)
                    if best is None or score > best[0]:
                        best = (score, q, sal, cost, val)
        if best is None or not bank or not code:
            return LayoutSolveResult(False, section, {}, {"ok": False, "messages": ["b_math_or_identity_not_found"]}, hypotheses_tested=tested)
        _, q, sal, cost, val = best
        qcol, qtxt, _ = q; scol, stxt, _ = sal; ccol, ctxt, _ = cost
        used_cols = {c.column_id for c in [bank_col, code_col, qcol, scol, ccol] if c is not None}
        row = {"codigo": code, "banco": bank, "mao_obra": self._description(cols, used_cols, section), "quantidade": qtxt, "salario_hora": stxt, "custo_horario": ctxt}
        return LayoutSolveResult(True, section, row, val.as_dict(), {}, self._unknowns(cols, used_cols), self._score_layout(cols, val.ok, len(used_cols)), tested, {"strategy": "b_math_combo"})

    def _solve_a(self, section: str, cols: List[LayoutColumn]) -> LayoutSolveResult:
        bank_col, bank = self._first_bank(cols)
        code_col, code = self._first_code(cols, section)
        nums = self._num_candidates(cols)[-8:]
        best = None; tested = 0
        for combo in combinations(nums, 6):
            for perm in permutations(combo, 6):
                tested += 1
                q, uop, uimp, cop, cimp, cost = perm
                qd, uopd, uimpd, copd, cimpd, cd = [x[2] for x in perm]
                val = self.engine._validate("quantidade * (utilizacao_operativa*custo_operacional_operativa + utilizacao_improdutiva*custo_operacional_improdutiva)", qd * ((uopd * copd) + (uimpd * cimpd)), cd)
                if val.ok:
                    visual_bonus = 0.10 if all(perm[i][0].cx <= perm[i+1][0].cx for i in range(5)) else 0.0
                    score = sum(x[0].confidence for x in perm) + visual_bonus
                    if best is None or score > best[0]: best = (score, perm, val)
        if best is None or not bank or not code:
            return LayoutSolveResult(False, section, {}, {"ok": False, "messages": ["a_math_or_identity_not_found"]}, hypotheses_tested=tested)
        _, perm, val = best
        q, uop, uimp, cop, cimp, cost = perm
        used_cols = {c.column_id for c in [bank_col, code_col, *(x[0] for x in perm)] if c is not None}
        row = {"codigo": code, "banco": bank, "equipamento": self._description(cols, used_cols, section), "quantidade": q[1], "utilizacao": {"operativa": uop[1], "improdutiva": uimp[1]}, "custo_operacional": {"operativa": cop[1], "improdutiva": cimp[1]}, "custo_horario": cost[1]}
        return LayoutSolveResult(True, section, row, val.as_dict(), {}, self._unknowns(cols, used_cols), self._score_layout(cols, val.ok, len(used_cols)), tested, {"strategy": "a_math_combo"})

    def _solve_f(self, section: str, cols: List[LayoutColumn]) -> LayoutSolveResult:
        # Full F reconstruction is still delegated to the section_f engine in the parser.
        # Here we provide a robust identity/unknown classifier for layout mutation tests.
        bank_col, bank = self._first_bank(cols)
        code_col, code = self._first_code(cols, section)
        unit_candidates = self._unit_candidates(cols, section)
        nums = self._num_candidates(cols)
        if not bank or not code or not nums:
            return LayoutSolveResult(False, section, {}, {"ok": False, "messages": ["f_identity_not_found"]})
        unit_col, unit = unit_candidates[0] if unit_candidates else (None, "tkm")
        cost = nums[-1]
        row = {"banco": bank, "insumo": code, "momento_transporte": self._description(cols, {c.column_id for c in [bank_col, code_col, unit_col, cost[0]] if c}, section), "quantidade": nums[0][1], "unidade": unit, "custo_horario": cost[1]}
        used_cols = {c.column_id for c in [bank_col, code_col, unit_col, cost[0], nums[0][0]] if c is not None}
        return LayoutSolveResult(True, section, row, {"ok": True, "formula": "f_identity_layout_only"}, {}, self._unknowns(cols, used_cols), self._score_layout(cols, True, len(used_cols)), 1, {"strategy": "f_identity_layout"})


def make_columns_from_order(values: Dict[str, Any], order: Sequence[str], extra: Dict[str, Any] | None = None, start_x: float = 50.0, width: float = 52.0) -> List[Dict[str, Any]]:
    """Helper used by tests to simulate shifted/reordered/extra columns."""
    extra = extra or {}
    merged: Dict[str, Any] = {**values, **extra}
    cols: List[Dict[str, Any]] = []
    x = start_x
    for name in order:
        raw = merged.get(name, "")
        vals = raw if isinstance(raw, list) else [raw]
        cols.append({"column_id": name, "x0": x, "x1": x + width, "header": name, "values": [str(v) for v in vals if str(v) != ""]})
        x += width + 6.0
    return cols


def reflow_description_fragments(rows: List[Dict[str, Any]], description_field: str, fragments: Sequence[Dict[str, Any]], desc_band: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Attach wrapped description fragments to the previous row when they fall inside the learned description band.

    This is a small, deterministic helper for the parser/profile layer. It does not
    guess text outside the band. Fragments should provide at least: text, x0, x1.
    """
    if not rows or not desc_band or desc_band.get("x0") is None or desc_band.get("x1") is None:
        return rows
    x0 = float(desc_band["x0"]); x1 = float(desc_band["x1"])
    for frag in fragments:
        fx0 = float(frag.get("x0", -9999)); fx1 = float(frag.get("x1", -9999)); text = clean(frag.get("text"))
        if not text:
            continue
        tk = key(text)
        if tk.startswith("DERACRE PAGINA") or tk.startswith("SEDUR PAGINA") or "PAGINA" in tk and any(ch.isdigit() for ch in tk):
            continue
        if parse_decimal(text) is not None:
            continue
        # Require meaningful overlap with description band.
        overlap = max(0.0, min(fx1, x1) - max(fx0, x0))
        frag_w = max(1.0, fx1 - fx0)
        if overlap / frag_w >= 0.55:
            rows[-1][description_field] = clean(f"{rows[-1].get(description_field, '')} {text}")
            rows[-1].setdefault("_description_reflow", []).append({"text": text, "reason": "fragment_inside_learned_description_band"})
    return rows
