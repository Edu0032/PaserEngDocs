from __future__ import annotations

"""Numeric constraint solver for public budget/composition rows.

The solver is intentionally conservative: it only fills a missing public numeric
field when two sibling values are already present and the algebra is exact enough
for budget/composition contracts.  It never overwrites a non-empty field.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import math
import re

VERSION = "v61.0.75-correction-output-contract-and-review-index"


_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?(?:\.\d{3})*(?:,\d+)?$")


def parse_ptbr_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
            return f if math.isfinite(f) else None
        except Exception:
            return None
    text = str(value).strip().replace("\u00a0", " ").replace(" ", "")
    if not text:
        return None
    # Keep codes such as 12345/001, CP-120, CADM.01 out of numeric parsing.
    if "/" in text or re.search(r"[A-Za-zÁ-ÿ]", text):
        return None
    if not re.match(r"^-?[\d.,]+$", text):
        return None
    # pt-BR: 1.234,56. If both separators exist, dots are thousands.
    if "," in text:
        normalized = text.replace(".", "").replace(",", ".")
    else:
        # A lone dot with exactly three trailing digits is usually thousands in
        # public Brazilian budgets; otherwise it may be a decimal.
        parts = text.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            normalized = text.replace(".", "")
        else:
            normalized = text
    try:
        f = float(normalized)
    except Exception:
        return None
    return f if math.isfinite(f) else None


def format_ptbr_number(value: float, *, decimals: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return ""
    s = f"{float(value):,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _is_empty(value: Any) -> bool:
    return value in (None, "")


@dataclass
class NumericRepair:
    path: List[Any]
    field: str
    value: str
    rule: str
    evidence: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "path": list(self.path),
            "field": self.field,
            "value": self.value,
            "rule": self.rule,
            "evidence": dict(self.evidence),
        }


def solve_triplet_missing(
    row: Dict[str, Any],
    *,
    path: List[Any],
    quantity_field: str,
    unit_field: str,
    total_field: str,
    unit_decimals: int = 2,
    total_decimals: int = 2,
    quantity_decimals: int = 7,
    rule_prefix: str,
) -> List[NumericRepair]:
    """Fill one missing field in ``q * unit = total`` if exactly one is empty."""
    q_raw = row.get(quantity_field)
    u_raw = row.get(unit_field)
    t_raw = row.get(total_field)
    q = parse_ptbr_number(q_raw)
    u = parse_ptbr_number(u_raw)
    t = parse_ptbr_number(t_raw)
    empty = [
        quantity_field if _is_empty(q_raw) else None,
        unit_field if _is_empty(u_raw) else None,
        total_field if _is_empty(t_raw) else None,
    ]
    empty = [x for x in empty if x]
    if len(empty) != 1:
        return []
    missing = empty[0]
    repairs: List[NumericRepair] = []
    if missing == total_field and q is not None and u is not None:
        val = q * u
        repairs.append(NumericRepair(path + [total_field], total_field, format_ptbr_number(val, decimals=total_decimals), f"{rule_prefix}:total=q_times_unit", {quantity_field: q_raw, unit_field: u_raw}))
    elif missing == unit_field and q not in (None, 0) and t is not None:
        val = t / q
        repairs.append(NumericRepair(path + [unit_field], unit_field, format_ptbr_number(val, decimals=unit_decimals), f"{rule_prefix}:unit=total_div_q", {quantity_field: q_raw, total_field: t_raw}))
    elif missing == quantity_field and u not in (None, 0) and t is not None:
        val = t / u
        repairs.append(NumericRepair(path + [quantity_field], quantity_field, format_ptbr_number(val, decimals=quantity_decimals), f"{rule_prefix}:q=total_div_unit", {unit_field: u_raw, total_field: t_raw}))
    return repairs



def build_triplet_expectations(
    row: Dict[str, Any],
    *,
    quantity_field: str,
    unit_field: str,
    total_field: str,
    unit_decimals: int = 2,
    total_decimals: int = 2,
    quantity_decimals: int = 7,
    rule_prefix: str,
) -> List[Dict[str, Any]]:
    """Return math-only expected values without mutating public fields.

    v61.0.40 rule: algebra can guide search and validation, but it is not
    physical/extracted evidence.  Callers may store these expectations under
    _calc and use them to look for matching candidates in the same row/nearby
    fragments; they must not copy the value into the public field unless a
    matching candidate is found in PDF/extracted evidence.
    """
    repairs = solve_triplet_missing(
        row,
        path=[],
        quantity_field=quantity_field,
        unit_field=unit_field,
        total_field=total_field,
        unit_decimals=unit_decimals,
        total_decimals=total_decimals,
        quantity_decimals=quantity_decimals,
        rule_prefix=rule_prefix,
    )
    out: List[Dict[str, Any]] = []
    for repair in repairs:
        out.append({
            "field": repair.field,
            "expected_value": repair.value,
            "rule": repair.rule,
            "evidence_grade": "math_only_expected",
            "public_write_allowed": False,
            "evidence": repair.evidence,
        })
    return out


def math_triplet_status(row: Dict[str, Any], *, quantity_field: str, unit_field: str, total_field: str, tolerance: float = 0.05) -> Dict[str, Any]:
    q = parse_ptbr_number(row.get(quantity_field))
    u = parse_ptbr_number(row.get(unit_field))
    t = parse_ptbr_number(row.get(total_field))
    if q is None or u is None or t is None:
        return {"status": "missing_values", "ok": False, "missing": [f for f, v in ((quantity_field, q), (unit_field, u), (total_field, t)) if v is None]}
    calc = q * u
    delta = abs(calc - t)
    return {"status": "ok" if delta <= tolerance else "mismatch", "ok": delta <= tolerance, "calc": round(calc, 6), "expected": t, "delta": round(delta, 6), "tolerance": tolerance}
