from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

NUM_RE = r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?"
BANK_RE = r"SICRO\s*(?:2|3)?"


def strip_accents(text: Any) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", str(text or "")) if unicodedata.category(ch) != "Mn")


def clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("\xa0", " ")).strip()


def key(text: Any) -> str:
    return strip_accents(clean(text)).upper()


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "config" / "base_config.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_decimal(text: Any) -> Optional[Decimal]:
    raw = clean(text).replace("R$", "").strip()
    if not re.fullmatch(NUM_RE, raw):
        return None
    try:
        return Decimal(raw.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def dec_to_ptbr(value: Decimal | None, places: int | None = None) -> str:
    if value is None:
        return ""
    v = value
    if places is not None:
        q = Decimal("1").scaleb(-places)
        v = value.quantize(q, rounding=ROUND_HALF_UP)
    text = format(v, "f")
    if "." not in text:
        return text
    inteiro, frac = text.split(".", 1)
    return f"{inteiro},{frac}"


def normalize_code(text: Any) -> str:
    raw = clean(text).replace(" ", "")
    m = re.fullmatch(r"([EMPemp])0*(\d{3,6})", raw)
    if m:
        return f"{m.group(1).upper()}{m.group(2).zfill(4)}" if len(m.group(2)) < 4 else f"{m.group(1).upper()}{m.group(2)}"
    return raw.upper()


@dataclass
class NumberToken:
    text: str
    value: Decimal


@dataclass
class RowValidation:
    ok: bool = True
    formula: str = ""
    calculated: str = ""
    expected: str = ""
    delta: str = ""
    tolerance: str = ""
    messages: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in {
            "ok": self.ok,
            "formula": self.formula,
            "calculated": self.calculated,
            "expected": self.expected,
            "delta": self.delta,
            "tolerance": self.tolerance,
            "messages": self.messages,
        }.items() if v not in ("", [], None)}


@dataclass
class ParsedRow:
    section: str
    public_key: str
    row: Dict[str, Any]
    validation: RowValidation
    raw_text: str


class SicroEngine:
    """Domain-driven SICRO parser/validator.

    This engine is deliberately independent from the monorepo parser. It contains the
    reusable SICRO knowledge: valid banks, code families, short unit tokens, section
    schemas and section-specific math. The extractor must call this class for every
    row; regex-only parsing outside this engine should not be necessary.
    """

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or load_config()
        self.sicro = self.config.get("sicro", {})
        self.valid_banks = set(self.sicro.get("banks", {}).get("valid", ["SICRO", "SICRO2", "SICRO3"]))
        self.bank_normalization = self.sicro.get("banks", {}).get("normalization", {})
        self.code_patterns = self.sicro.get("code_patterns", {})
        self.units = self.sicro.get("units", {})
        self.sections = self.sicro.get("sections", {})
        val = self.sicro.get("validation", {})
        self.row_tol = Decimal(str(val.get("row_tolerance_abs", "0.0100")))
        self.section_tol = Decimal(str(val.get("section_tolerance_abs", "0.0200")))

    # ---------- classifiers ----------
    def normalize_bank(self, token: Any) -> str:
        raw = key(token).replace(" ", "")
        if raw == "SICRO2":
            return "SICRO2"
        if raw == "SICRO3":
            return "SICRO3"
        if raw == "SICRO":
            return "SICRO"
        return self.bank_normalization.get(key(token), raw)

    def is_bank(self, token: Any) -> bool:
        return self.normalize_bank(token) in self.valid_banks

    def classify_code(self, token: Any) -> str:
        raw = normalize_code(token)
        for name, pattern in self.code_patterns.items():
            if re.fullmatch(pattern, raw, flags=re.IGNORECASE):
                if name in {"composicao", "servico_auxiliar", "servico_tempo_fixo", "servico_transporte"} and raw.isdigit():
                    return name
                if name in {"equipamento", "mao_obra", "material"}:
                    return name
        if re.fullmatch(r"E\d{3,5}", raw, flags=re.I):
            return "equipamento"
        if re.fullmatch(r"P\d{3,5}", raw, flags=re.I):
            return "mao_obra"
        if re.fullmatch(r"M\d{3,5}", raw, flags=re.I):
            return "material"
        if re.fullmatch(r"\d{7}", raw):
            return "composicao"
        return ""

    def is_unit(self, token: Any, section: str | None = None) -> bool:
        raw = clean(token)
        raw_key = key(raw).replace("²", "2").replace("³", "3")
        candidates: List[str] = []
        if section:
            candidates.extend(self.units.get("by_section", {}).get(section, []))
        candidates.extend(self.units.get("common", []))
        normalized = {key(u).replace("²", "2").replace("³", "3") for u in candidates}
        if raw_key in normalized:
            return True
        return len(raw) <= int(self.units.get("short_token_max_len", 4)) and parse_decimal(raw) is None and not self.classify_code(raw) and not self.is_bank(raw)

    def resolve_code_bank(self, first: Any, second: Any) -> Tuple[str, str, Dict[str, Any]]:
        f = clean(first); s = clean(second)
        ev = {
            "first": f, "second": s,
            "first_is_bank": self.is_bank(f), "second_is_bank": self.is_bank(s),
            "first_code_type": self.classify_code(f), "second_code_type": self.classify_code(s),
        }
        if ev["first_is_bank"] and ev["second_code_type"]:
            return normalize_code(s), self.normalize_bank(f), ev
        if ev["second_is_bank"] and ev["first_code_type"]:
            return normalize_code(f), self.normalize_bank(s), ev
        if ev["first_code_type"]:
            return normalize_code(f), self.normalize_bank(s), ev
        if ev["second_code_type"]:
            return normalize_code(s), self.normalize_bank(f), ev
        return normalize_code(f), self.normalize_bank(s), ev

    # ---------- generic helpers ----------
    def numbers(self, text: str) -> List[NumberToken]:
        out: List[NumberToken] = []
        for m in re.finditer(NUM_RE, text):
            dec = parse_decimal(m.group(0))
            if dec is not None:
                out.append(NumberToken(m.group(0), dec))
        return out

    def _validate(self, formula: str, calculated: Decimal, expected: Decimal, tolerance: Decimal | None = None) -> RowValidation:
        tol = tolerance or self.row_tol
        delta = abs(calculated - expected)
        ok = delta <= tol
        return RowValidation(
            ok=ok,
            formula=formula,
            calculated=dec_to_ptbr(calculated, 6).rstrip("0").rstrip(","),
            expected=dec_to_ptbr(expected),
            delta=dec_to_ptbr(delta, 6).rstrip("0").rstrip(","),
            tolerance=dec_to_ptbr(tol),
            messages=[] if ok else [f"Divergência matemática: {formula}"],
        )

    def _with_validation(self, section: str, row: Dict[str, Any], validation: RowValidation, raw_text: str) -> ParsedRow:
        return ParsedRow(section=section, public_key=self.sections.get(section, {}).get("public_key", section), row=row, validation=validation, raw_text=raw_text)

    # ---------- principal ----------
    def _move_trailing_principal_description_before_numeric_tail(self, raw: str) -> str:
        """Repair principal rows where a wrapped description line appears after
        the numeric tail in text order. Example:
        ``... - carga e t 1,0000000 33,34 33,34 descarga manuais`` should become
        ``... - carga e descarga manuais t 1,0000000 33,34 33,34``.
        """
        m0 = re.match(rf"^(?P<head>Composi(?:ç[aã]o|cao)\s+\d{{7}}\s+{BANK_RE}\s+)(?P<body>.+)$", raw, flags=re.I)
        if not m0:
            return raw
        body = clean(m0.group("body"))
        pat = rf"(?P<tail>\s+(?P<unit>\S{{1,8}})\s+(?P<q>{NUM_RE})\s+(?P<unit_cost>{NUM_RE})\s+(?P<total>{NUM_RE}))"
        chosen = None
        for m in re.finditer(pat, body, flags=re.I):
            if self.is_unit(m.group("unit"), "principal"):
                chosen = m
        if not chosen:
            return raw
        extra = clean(body[chosen.end():])
        if not extra:
            return raw
        # Do not move footers, headers or number-heavy fragments into the service.
        if self.is_footer_or_header_noise(extra) or self.parse_summary(extra):
            return raw
        # Descriptions frequently contain dimensions/weights (e.g. 3,40 m³, 15 t).
        # Reject only fragments that are purely/mostly numeric; allow textual
        # fragments with embedded numbers.
        alpha_count = len(re.findall(r"[A-Za-zÀ-ÿ]", extra))
        if re.search(NUM_RE, extra) and alpha_count < 3:
            return raw
        if any(x in key(extra) for x in ("CODIGO", "BANCO", "CUSTO", "VALOR", "PAGINA")):
            return raw
        head_body = clean(body[:chosen.start()])
        return clean(f"{m0.group('head')} {head_body} {extra} {chosen.group('tail')}")

    def parse_principal(self, text: str, _allow_repair: bool = True) -> Optional[Dict[str, Any]]:
        raw = clean(text)
        m = re.match(rf"^Composi(?:ç[aã]o|cao)\s+(?P<code>\d{{7}})\s+(?P<bank>{BANK_RE})\s+(?P<body>.+)$", raw, flags=re.I)
        if not m:
            return None
        body = clean(m.group("body"))
        tail = re.search(rf"\s(?P<unit>\S{{1,6}})\s+(?P<quant>{NUM_RE})\s+(?P<unit_cost>{NUM_RE})\s+(?P<total>{NUM_RE})\s*$", body)
        if not tail:
            repaired = self._move_trailing_principal_description_before_numeric_tail(raw)
            if _allow_repair and repaired != raw:
                return self.parse_principal(repaired, _allow_repair=False)
            return None
        unit = tail.group("unit")
        if not self.is_unit(unit, "principal"):
            return None
        q = parse_decimal(tail.group("quant")); unit_cost = parse_decimal(tail.group("unit_cost")); total = parse_decimal(tail.group("total"))
        desc = clean(body[:tail.start()])
        calc = (q or Decimal(0)) * (unit_cost or Decimal(0))
        val = self._validate("quantidade * custo_unitario", calc, total or Decimal(0), Decimal("0.05"))
        return {
            "codigo": normalize_code(m.group("code")),
            "banco": self.normalize_bank(m.group("bank")),
            "servico": desc,
            "unidade": unit,
            "quantidade": tail.group("quant"),
            "custo_unitario": tail.group("unit_cost"),
            "custo_total": tail.group("total"),
            "validacao": val.as_dict(),
            "raw_text": raw,
        }

    # ---------- section rows ----------
    def _move_trailing_description_before_numeric_tail(self, section: str, raw: str) -> str:
        """Repair wrapped SICRO rows where right-side numeric columns are emitted
        before a second description line. The repair uses the domain unit registry
        so a 7-digit code is not mistaken for quantity.
        """
        if section not in {"C", "D", "E"}:
            return raw
        if section in {"C", "D"}:
            pat = rf"(?P<tail>\s+(?P<q>{NUM_RE})\s+(?P<unit>\S{{1,8}})\s+(?P<price>{NUM_RE})\s+(?P<cost>{NUM_RE}))"
        else:
            pat = rf"(?P<tail>\s+(?P<code>\d{{7}})\s+(?P<q>{NUM_RE})\s+(?P<unit>\S{{1,8}})\s+(?P<price>{NUM_RE})\s+(?P<cost>{NUM_RE}))"
        chosen = None
        for m in re.finditer(pat, raw, flags=re.I):
            if self.is_unit(m.group("unit"), section):
                chosen = m
        if not chosen:
            return raw
        extra = clean(raw[chosen.end():])
        if not extra or re.search(NUM_RE, extra):
            return raw
        if any(x in key(extra) for x in ("CUSTO TOTAL", "MO SEM LS", "VALOR DO BDI", "BANCO", "CODIGO")):
            return raw
        head = raw[:chosen.start()]
        tail = chosen.group("tail")
        return clean(f"{head} {extra} {tail}")

    def parse_section_columns(self, section: str, columns: List[Dict[str, Any]]) -> Optional[ParsedRow]:
        """Parse a SICRO row from content-classified columns.

        This is the v61.0.20 layout-hardening entrypoint. It handles reordered
        columns and extra/unknown columns by delegating role assignment and math
        hypothesis solving to LayoutHypothesisSolver. It is intentionally optional:
        classic regex remains fast for normal rows, and this method is used when
        layout mutation, a weak row, or a future grid extractor supplies columns.
        """
        try:
            from .sicro_layout import LayoutHypothesisSolver
            solved = LayoutHypothesisSolver(self).solve(section, columns)
        except Exception:
            return None
        if not solved.ok:
            return None
        row = dict(solved.row)
        row["_layout"] = {
            "version": "v61.0.20-sicro-audit-confidence-boundary",
            "canonical_columns": solved.canonical_columns,
            "unknown_columns": solved.unknown_columns,
            "layout_confidence": solved.layout_confidence,
            "hypotheses_tested": solved.hypotheses_tested,
            "chosen_hypothesis": solved.chosen_hypothesis,
        }
        return self._with_validation(section, row, RowValidation(**{k: v for k, v in solved.validation.items() if k in RowValidation.__annotations__}), "columns")

    def _raw_text_to_token_columns(self, raw: str) -> List[Dict[str, Any]]:
        tokens = [t for t in clean(raw).split(" ") if t]
        cols: List[Dict[str, Any]] = []
        x = 40.0
        for idx, tok in enumerate(tokens):
            cols.append({"column_id": f"tok_{idx}", "x0": x, "x1": x + max(8.0, len(tok) * 4.0), "values": [tok], "header": ""})
            x += max(12.0, len(tok) * 4.0) + 4.0
        return cols

    def _attempt_layout_flexible_parse(self, section: str, raw: str) -> Optional[ParsedRow]:
        # Flexible content parsing is most useful for C/D/E/B rows when columns
        # are shifted/reordered or a harmless unknown column appears.
        # Raw-token layout solving is intentionally disabled by default because
        # real PDF lines can contain long descriptions and many short tokens. The
        # production path should supply real column candidates from geometry; the
        # public parse_section_columns() entrypoint remains fully enabled for that.
        if not self.sicro.get("layout_hardening", {}).get("enable_raw_text_layout_fallback", False):
            return None
        if section not in {"B", "C", "D", "E"}:
            return None
        if len(raw.split()) > 28:
            return None
        parsed = self.parse_section_columns(section, self._raw_text_to_token_columns(raw))
        if parsed is not None:
            parsed.row.setdefault("_layout", {})["source"] = "raw_text_token_columns"
        return parsed

    def parse_section_row(self, section: str, text: str) -> Optional[ParsedRow]:
        method = getattr(self, f"_parse_{section.lower()}", None)
        if not method:
            return None
        raw = clean(text)
        parsed = method(raw)
        if parsed is not None:
            return self._attempt_math_recovery(section, parsed, raw)
        flexible = self._attempt_layout_flexible_parse(section, raw)
        if flexible is not None:
            return self._attempt_math_recovery(section, flexible, raw)
        repaired = self._move_trailing_description_before_numeric_tail(section, raw)
        if repaired != raw:
            parsed = method(repaired)
            if parsed is not None:
                return self._attempt_math_recovery(section, parsed, repaired)
            flexible = self._attempt_layout_flexible_parse(section, repaired)
            if flexible is not None:
                return self._attempt_math_recovery(section, flexible, repaired)
        return None

    def _attempt_math_recovery(self, section: str, parsed: ParsedRow, raw: str) -> ParsedRow:
        """Use mathematics as an automatic repair tool, not only an error report.

        The repair is conservative: it only rewrites numeric columns when the
        current line fails and an alternative ordering closes within tolerance.
        This catches common PDF-column swaps without changing rows that already
        validate.
        """
        if parsed.validation.ok:
            return parsed
        row = dict(parsed.row)
        if section in {"C", "D", "E"}:
            nums = [n.text for n in self.numbers(raw)]
            # The right-most values carry quantity/preco/custo in C-D-E. Descriptions
            # may contain numbers, so test only the final numeric window.
            tail = nums[-5:] if len(nums) >= 3 else nums
            best = None
            for i, q_text in enumerate(tail):
                for j, price_text in enumerate(tail):
                    for k, cost_text in enumerate(tail):
                        if len({i, j, k}) < 3:
                            continue
                        q = parse_decimal(q_text) or Decimal(0)
                        price = parse_decimal(price_text) or Decimal(0)
                        cost = parse_decimal(cost_text) or Decimal(0)
                        val = self._validate("quantidade * preco_unitario", q * price, cost)
                        delta = parse_decimal(val.delta) or Decimal(999999)
                        if val.ok and (best is None or delta < best[0]):
                            best = (delta, q_text, price_text, cost_text, val)
            if best:
                _, q_text, price_text, cost_text, val = best
                row["quantidade"] = q_text
                row["preco_unitario"] = price_text
                row["custo_horario"] = cost_text
                row["_recovery"] = {
                    "applied": True,
                    "strategy": "math_permutation_tail",
                    "original_validation": parsed.validation.as_dict(),
                    "raw_text": raw,
                }
                return self._with_validation(section, row, val, raw)
        if section == "B":
            nums = [n.text for n in self.numbers(raw)][-4:]
            best = None
            for i, q_text in enumerate(nums):
                for j, sal_text in enumerate(nums):
                    for k, cost_text in enumerate(nums):
                        if len({i, j, k}) < 3:
                            continue
                        q = parse_decimal(q_text) or Decimal(0)
                        sal = parse_decimal(sal_text) or Decimal(0)
                        cost = parse_decimal(cost_text) or Decimal(0)
                        val = self._validate("quantidade * salario_hora", q * sal, cost)
                        delta = parse_decimal(val.delta) or Decimal(999999)
                        if val.ok and (best is None or delta < best[0]):
                            best = (delta, q_text, sal_text, cost_text, val)
            if best:
                _, q_text, sal_text, cost_text, val = best
                row["quantidade"] = q_text
                row["salario_hora"] = sal_text
                row["custo_horario"] = cost_text
                row["_recovery"] = {"applied": True, "strategy": "math_permutation_tail", "original_validation": parsed.validation.as_dict(), "raw_text": raw}
                return self._with_validation(section, row, val, raw)
        return parsed

    def _parse_a(self, raw: str) -> Optional[ParsedRow]:
        m = re.match(rf"^(?:Insumo\s+)?(?P<code>E\s*\d{{3,5}})\s+(?P<bank>{BANK_RE})\s+(?P<desc>.+?)\s+(?P<q>{NUM_RE})\s+(?P<uop>{NUM_RE})\s+(?P<uimp>{NUM_RE})\s+(?P<cop>{NUM_RE})\s+(?P<cimp>{NUM_RE})\s+(?P<cost>{NUM_RE})$", raw, flags=re.I)
        if not m:
            return None
        q, uop, uimp, cop, cimp, cost = [parse_decimal(m.group(g)) or Decimal(0) for g in ("q", "uop", "uimp", "cop", "cimp", "cost")]
        calc = q * ((uop * cop) + (uimp * cimp))
        val = self._validate("quantidade * (utilizacao_operativa*custo_operacional_operativa + utilizacao_improdutiva*custo_operacional_improdutiva)", calc, cost)
        row = {
            "codigo": normalize_code(m.group("code")), "banco": self.normalize_bank(m.group("bank")),
            "equipamento": clean(m.group("desc")), "quantidade": m.group("q"),
            "utilizacao": {"operativa": m.group("uop"), "improdutiva": m.group("uimp")},
            "custo_operacional": {"operativa": m.group("cop"), "improdutiva": m.group("cimp")},
            "custo_horario": m.group("cost"),
        }
        return self._with_validation("A", row, val, raw)

    def _parse_b(self, raw: str) -> Optional[ParsedRow]:
        m = re.match(rf"^(?:Insumo\s+)?(?P<code>P\s*\d{{3,5}})\s+(?P<bank>{BANK_RE})\s+(?P<desc>.+?)\s+(?P<q>{NUM_RE})\s+(?P<sal>{NUM_RE})\s+(?P<cost>{NUM_RE})$", raw, flags=re.I)
        if not m:
            return None
        q, sal, cost = [parse_decimal(m.group(g)) or Decimal(0) for g in ("q", "sal", "cost")]
        val = self._validate("quantidade * salario_hora", q * sal, cost)
        row = {"codigo": normalize_code(m.group("code")), "banco": self.normalize_bank(m.group("bank")), "mao_obra": clean(m.group("desc")), "quantidade": m.group("q"), "salario_hora": m.group("sal"), "custo_horario": m.group("cost")}
        return self._with_validation("B", row, val, raw)

    def _parse_c(self, raw: str) -> Optional[ParsedRow]:
        m = re.match(rf"^Insumo\s+(?P<bank>{BANK_RE})\s+(?P<code>M\s*\d{{3,5}})\s+(?P<desc>.+?)\s+(?P<q>{NUM_RE})\s+(?P<unit>\S{{1,6}})\s+(?P<price>{NUM_RE})\s+(?P<cost>{NUM_RE})$", raw, flags=re.I)
        if not m:
            return None
        if not self.is_unit(m.group("unit"), "C"):
            return None
        q, price, cost = [parse_decimal(m.group(g)) or Decimal(0) for g in ("q", "price", "cost")]
        val = self._validate("quantidade * preco_unitario", q * price, cost)
        row = {"banco": self.normalize_bank(m.group("bank")), "codigo": normalize_code(m.group("code")), "material": clean(m.group("desc")), "quantidade": m.group("q"), "unidade": m.group("unit"), "preco_unitario": m.group("price"), "custo_horario": m.group("cost")}
        return self._with_validation("C", row, val, raw)

    def _parse_d(self, raw: str) -> Optional[ParsedRow]:
        m = re.match(rf"^(?:Atividade\s+Auxiliar|Composi(?:ç[aã]o|cao)\s+Auxiliar|Auxiliar)\s+(?P<bank>{BANK_RE})\s+(?P<code>\d{{7}})\s+(?P<desc>.+?)\s+(?P<q>{NUM_RE})\s+(?P<unit>\S{{1,6}})\s+(?P<price>{NUM_RE})\s+(?P<cost>{NUM_RE})$", raw, flags=re.I)
        if not m:
            return None
        if not self.is_unit(m.group("unit"), "D"):
            return None
        q, price, cost = [parse_decimal(m.group(g)) or Decimal(0) for g in ("q", "price", "cost")]
        val = self._validate("quantidade * preco_unitario", q * price, cost)
        row = {"banco": self.normalize_bank(m.group("bank")), "codigo": normalize_code(m.group("code")), "atividade_auxiliar": clean(m.group("desc")), "quantidade": m.group("q"), "unidade": m.group("unit"), "preco_unitario": m.group("price"), "custo_horario": m.group("cost")}
        return self._with_validation("D", row, val, raw)

    def _parse_e(self, raw: str) -> Optional[ParsedRow]:
        m = re.match(rf"^Tempo\s+Fixo\s+(?P<bank>{BANK_RE})\s+(?P<insumo>M\s*\d{{3,5}})\s+(?P<desc>.+?)\s+(?P<code>\d{{7}})\s+(?P<q>{NUM_RE})\s+(?P<unit>\S{{1,6}})\s+(?P<price>{NUM_RE})\s+(?P<cost>{NUM_RE})$", raw, flags=re.I)
        if not m:
            return None
        if not self.is_unit(m.group("unit"), "E"):
            return None
        q, price, cost = [parse_decimal(m.group(g)) or Decimal(0) for g in ("q", "price", "cost")]
        val = self._validate("quantidade * preco_unitario", q * price, cost)
        row = {"banco": self.normalize_bank(m.group("bank")), "insumo": normalize_code(m.group("insumo")), "tempo_fixo": clean(m.group("desc")), "codigo": normalize_code(m.group("code")), "quantidade": m.group("q"), "unidade": m.group("unit"), "preco_unitario": m.group("price"), "custo_horario": m.group("cost")}
        return self._with_validation("E", row, val, raw)

    def _parse_f(self, raw: str) -> Optional[ParsedRow]:
        normalized = clean(raw.replace("Momento de Transporte", "Momento de").replace("Transporte SICRO", "SICRO"))
        m = re.match(rf"^(?:Momento\s+de\s+)?(?P<bank>{BANK_RE})\s+(?P<insumo>M\s*\d{{3,5}})\s+(?P<body>.+)$", normalized, flags=re.I)
        if not m:
            return None
        body = m.group("body")
        code_pat = r"(?<![,\.\d])\d{7}(?![,\.\d])"
        first_code = re.search(code_pat, body)
        if not first_code:
            return None
        prefix = clean(body[:first_code.start()])
        rest = clean(body[first_code.start():])
        qty_matches = []
        for qm in re.finditer(rf"(?P<q>{NUM_RE})\s+(?P<unit>\S{{1,8}})", prefix):
            if self.is_unit(qm.group("unit"), "F"):
                qty_matches.append(qm)
        if not qty_matches:
            return None
        qty_match = qty_matches[-1]
        desc = clean(prefix[:qty_match.start()])
        q_text = qty_match.group("q")
        unit = qty_match.group("unit")
        codes = re.findall(code_pat, rest)
        if len(codes) < 3:
            return None
        code3_end = 0
        found = 0
        for match in re.finditer(code_pat, rest):
            found += 1
            if found == 3:
                code3_end = match.end()
                break
        after_codes = rest[code3_end:]
        cost_match = re.search(rf"\b(?P<cost>\d+(?:,\d{{4,}}))\b", after_codes)
        cost_text = cost_match.group("cost") if cost_match else "0,0000"
        cost = parse_decimal(cost_text) or Decimal(0)
        dmt_values = [x.group(0) for x in re.finditer(r"\b\d+,\d{3}\b", after_codes)][:3]
        while len(dmt_values) < 3:
            dmt_values.append("0,000")
        prices = [pm.group(1) for pm in re.finditer(rf"R\$\s*({NUM_RE})", after_codes, flags=re.I)]
        while len(prices) < 3:
            prices.append("0,00")
        q = parse_decimal(q_text) or Decimal(0)
        dmt: Dict[str, Dict[str, str]] = {}
        calc = Decimal(0)
        for branch, code, dmt_q, price in zip(["LN", "RP", "P"], codes[:3], dmt_values[:3], prices[:3]):
            dmt_dec = parse_decimal(dmt_q) or Decimal(0)
            price_dec = parse_decimal(price) or Decimal(0)
            calc += q * dmt_dec * price_dec
            dmt[branch] = {"codigo": normalize_code(code), "quantidade_dmt": dmt_q, "preco_unitario_dmt": price}
        val = self._validate("sum(quantidade * quantidade_dmt * preco_unitario_dmt)", calc, cost)
        row = {"banco": self.normalize_bank(m.group("bank")), "insumo": normalize_code(m.group("insumo")), "momento_transporte": desc, "quantidade": q_text, "unidade": unit, "dmt": dmt, "custo_horario": cost_text}
        return self._with_validation("F", row, val, raw)

    # ---------- summary ----------
    def is_footer_or_header_noise(self, text: str) -> bool:
        k = key(text)
        noisy = (
            "DERACRE PAGINA", "SEDUR PAGINA", "RIO BRANCO", "ESTADO DO ACRE",
            "DEPARTAMENTO DE ESTRADAS", "OBJETO:", "CONVENIO:", "CONVÊNIO:",
            "MUNICIPIO:", "MUNICÍPIO:", "ENDERECO:", "ENDEREÇO:", "DATA-BASE",
            "COMPOSICOES ANALITICAS", "COMPOSIÇÕES ANALÍTICAS", "ANEXO",
        )
        return any(x in k for x in noisy)

    def _numbers_after_label(self, raw: str, alias: str) -> List[str]:
        raw_key = key(raw)
        alias_key = key(alias)
        pos = raw_key.find(alias_key)
        if pos < 0:
            return []
        # Use the original string slice around the same approximate offset. It is
        # intentionally simple and Pyodide-safe.
        tail = raw[max(0, pos):]
        return [m.group(0) for m in re.finditer(NUM_RE, tail)]

    def parse_summary(self, text: str) -> Dict[str, str]:
        raw = clean(text)
        out: Dict[str, str] = {}
        if not raw or self.is_footer_or_header_noise(raw):
            return out
        raw_k = key(raw)
        mo = re.search(rf"MO\s+sem\s+LS\s+({NUM_RE})\s+LS\s*=+>\s+({NUM_RE})\s+MO\s+com\s+LS\s*=+>\s+({NUM_RE})", raw, flags=re.I)
        if mo:
            out.update({"mo_sem_ls": mo.group(1), "ls": mo.group(2), "mo_com_ls": mo.group(3)})

        # BDI lines are footer-like and number-heavy; only capture them when the
        # exact labels are present.
        if "VALOR DO BDI" in raw_k:
            vals = self._numbers_after_label(raw, "Valor do BDI")
            if vals:
                out["valor_bdi"] = vals[0]
        if "VALOR COM BDI" in raw_k:
            vals = self._numbers_after_label(raw, "Valor com BDI")
            if vals:
                out["valor_com_bdi"] = vals[0]

        labels = self.sicro.get("summary_labels", {})
        for field, aliases in labels.items():
            if field in {"valor_bdi", "valor_com_bdi"}:
                continue
            for alias in aliases:
                if key(alias) in raw_k:
                    vals = self._numbers_after_label(raw, alias)
                    if vals:
                        # Summary totals have the value immediately after the label.
                        # This avoids choosing page numbers or footer dates later in the line.
                        out[field] = vals[0]
                    break
        return out

    # ---------- section aggregation ----------

    def validate_composition_summary(self, principal: Dict[str, Any], summaries: Dict[str, str]) -> Dict[str, Any]:
        """Cross-check principal values against SICRO footer/summary labels.

        Footers are number-heavy, so this method is conservative: lack of a
        summary is inconclusive, not an error. Divergences are only reported
        when the exact label was captured by parse_summary.
        """
        checks: List[Dict[str, Any]] = []
        issues: List[Dict[str, Any]] = []
        principal_unit = parse_decimal(principal.get("custo_unitario"))
        summary_unit = parse_decimal(summaries.get("preco_unitario"))
        if principal_unit is not None and summary_unit is not None:
            val = self._validate("principal.custo_unitario == resumo.preco_unitario", principal_unit, summary_unit, Decimal("0.05"))
            check = {"name": "preco_unitario_principal_vs_resumo", **val.as_dict()}
            checks.append(check)
            if not val.ok:
                issues.append(check)

        # When the usual SICRO components are present, use them as a second-level
        # consistency check. Missing components are normal in simplified/auxiliary
        # compositions and therefore marked as inconclusive.
        components = [
            "custo_unitario_execucao",
            "custo_total_material",
            "custo_total_atividades_auxiliares",
            "custo_total_tempos_fixos",
            "custo_total_momentos_transporte",
        ]
        present = [(name, parse_decimal(summaries.get(name))) for name in components if summaries.get(name) is not None]
        if principal_unit is not None and len(present) >= 2:
            calc = sum((v or Decimal(0)) for _, v in present)
            val = self._validate("soma_componentes_resumo ~= principal.custo_unitario", calc, principal_unit, Decimal("0.10"))
            check = {"name": "componentes_resumo_vs_principal", "components": [name for name, _ in present], **val.as_dict()}
            checks.append(check)
            # Do not fail for this aggregate unless all major components are present;
            # PDF footers often omit some totals or show them on nearby lines.
            if not val.ok and len(present) == len(components):
                issues.append(check)

        return {"ok": not issues, "status": "ok" if not issues else "divergente", "checks": checks, "issues": issues}

    def validate_section_total(self, rows: List[Dict[str, Any]], reported: str | None) -> RowValidation:
        total = Decimal(0)
        for row in rows:
            total += parse_decimal(row.get("custo_horario")) or Decimal(0)
        expected = parse_decimal(reported) if reported else None
        if expected is None:
            return RowValidation(ok=True, formula="sum(custo_horario)", calculated=dec_to_ptbr(total, 4), messages=["Total da seção não apareceu no texto extraído; total calculado foi preservado."])
        return self._validate("sum(custo_horario)", total, expected, self.section_tol)
