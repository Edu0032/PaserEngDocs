from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, OrcamentoItem, OrcamentoSintetico
from app.parser.code_value_classifier import clean_text, norm_text, looks_like_ptbr_decimal_or_money

VERSION = "v61.0.35-candidate-profile-consensus-engine"

TRUNCATION_TAILS = {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "E", "EM", "A", "O", "AO", "À", "AS"}
POLLUTION_TERMS = [
    "Custo Total das Atividades", "Valor com BDI", "Valor do BDI", "MO sem LS",
    "LS =>", "=>", "Total sem BDI", "Mão de Obra Mão de Obra",
]
CATEGORY_WORDS = ["MATERIAL", "INSUMO", "COMPOSICAO", "COMPOSIÇÃO", "AUXILIAR", "EQUIPAMENTO"]


def canon_bank(value: Any) -> str:
    text = norm_text(value).replace(" ", "")
    if text in {"SICRO", "SICRO2", "SICRO3", "DNIT"}:
        return "SICRO"
    if text in {"SINAPI", "CAIXA"}:
        return "SINAPI"
    if text in {"PROPRIO", "PRÓPRIO", "ANP"}:
        return "PRÓPRIO"
    return text or clean_text(value).upper()


def norm_code(value: Any) -> str:
    # Preserve slash, dash and dot.  Remove only spaces.
    return clean_text(value).upper().replace(" ", "")


def codebank(codigo: Any, banco: Any) -> str:
    c = norm_code(codigo)
    b = canon_bank(banco)
    return f"{c}|{b}" if c and b else ""


def is_sicro_bank(value: Any) -> bool:
    return canon_bank(value) == "SICRO"



def _has_suspicious_suffix_after_known_service(text: str) -> bool:
    norm = norm_text(text)
    marker = "COM ENCARGOS COMPLEMENTARES"
    if marker not in norm:
        return False
    suffix = norm.split(marker, 1)[1].strip(" -:.;")
    # Normal variants can have HORISTA/MENSALISTA/SINAPI date markers, but a long
    # title/category suffix means a header/group was appended to a real service.
    if not suffix:
        return False
    allowed = {"HORISTA", "MENSALISTA", "DIURNO", "NOTURNO"}
    toks = suffix.split()
    if len(toks) <= 2 and all(t in allowed for t in toks):
        return False
    return len(toks) >= 3


def _looks_like_concatenated_category_text(text: str) -> bool:
    # Generic signal: many title fragments joined into one description without a
    # SINAPI service anchor. This catches evidence graph pollution while avoiding
    # a hardcoded list of document section names.
    raw = clean_text(text)
    norm = norm_text(raw)
    separators = raw.count(" - ") + raw.count("; ") + raw.count(" | ")
    service_anchors = len(re.findall(r"\bAF_\d{2}/\d{4}\b", raw, flags=re.I))
    if separators >= 4 and service_anchors <= 1:
        return True
    if len(raw) < 160:
        return False
    # Many short uppercase/title chunks with no quantities usually indicate a
    # category/sidebar concatenation, not a single budget/composition description.
    chunks = re.split(r"\s{2,}|\s+-\s+|;|\|", raw)
    titleish = [c for c in chunks if 2 <= len(c.split()) <= 6 and not re.search(r"\d{1,3}(?:[.,]\d+)?", c)]
    return len(titleish) >= 5 and service_anchors == 0

def pollution_reason(text: Any) -> str:
    raw = clean_text(text)
    if not raw:
        return "empty_candidate"
    normalized = norm_text(raw)
    if _has_suspicious_suffix_after_known_service(raw):
        return "suspicious_suffix_after_encargos_complementares"
    if _looks_like_concatenated_category_text(raw):
        return "concatenated_category_text"
    for term in POLLUTION_TERMS:
        if norm_text(term) in normalized:
            return f"pollution_term:{term}"
    for word in CATEGORY_WORDS:
        if re.search(rf"\b{re.escape(word)}\b(?:\s+\b{re.escape(word)}\b)+", normalized):
            return "repeated_category_label"
    nums = re.findall(r"(?<![A-Z0-9])\d{1,3}(?:\.\d{3})*,\d{2,7}(?![A-Z0-9])", raw)
    if len(nums) >= 4:
        return "long_numeric_sequence"
    if raw.rstrip().endswith("=>"):
        return "summary_arrow_suffix"
    if re.fullmatch(r"[\d\s.,%/\-]+", raw):
        return "numeric_only_text"
    if len(raw) > 300 and "AF_" not in raw.upper():
        return "candidate_too_long_without_service_anchor"
    return ""


def is_truncated_text(text: Any) -> bool:
    raw = clean_text(text)
    if not raw:
        return False
    normalized = norm_text(raw)
    tail = (normalized.split() or [""])[-1]
    if tail in TRUNCATION_TAILS:
        return True
    if len(raw) < 32 and not re.search(r"\bAF_\d{2}/\d{4}\b", raw, flags=re.I):
        return True
    return False


def text_quality_score(text: Any) -> float:
    raw = clean_text(text)
    if not raw or pollution_reason(raw):
        return 0.0
    tokens = raw.split()
    score = min(len(raw) / 140.0, 1.0) * 3.0 + min(len(tokens) / 20.0, 1.0) * 2.0
    if re.search(r"\bAF_\d{2}/\d{4}\b", raw, flags=re.I):
        score += 0.8
    if any(ch in raw for ch in "()/-"):
        score += 0.25
    if is_truncated_text(raw):
        score -= 0.9
    if looks_like_ptbr_decimal_or_money(raw):
        score -= 3.0
    return round(max(score, 0.0), 4)


def similarity(a: Any, b: Any) -> float:
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na.startswith(nb) or nb.startswith(na):
        return 0.82 + min(len(na), len(nb)) / max(len(na), len(nb)) * 0.16
    return difflib.SequenceMatcher(None, na, nb).ratio()


@dataclass
class DescriptionEvidence:
    descricao: str
    score: float
    source: str
    occurrences: int = 1
    confirmed: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "descricao": self.descricao,
            "score": self.score,
            "source": self.source,
            "occurrences": self.occurrences,
            "confirmed": self.confirmed,
        }


def _all_budget_items(nodes: Iterable[OrcamentoItem]) -> Iterable[OrcamentoItem]:
    for node in nodes or []:
        yield node
        yield from _all_budget_items(getattr(node, "filhos", []) or [])


def _iter_blocks(comp: Composicoes):
    for collection, blocks in (("principais", comp.principais), ("auxiliares_globais", comp.auxiliares_globais)):
        for key, block in (blocks or {}).items():
            yield collection, key, block


def _iter_lines(block: BlocoComposicao) -> Iterable[Tuple[str, int | None, LinhaComposicao]]:
    if getattr(block, "principal", None) is not None:
        yield "principal", None, block.principal
    for idx, row in enumerate(block.composicoes_auxiliares or []):
        yield "composicoes_auxiliares", idx, row
    for idx, row in enumerate(block.insumos or []):
        yield "insumos", idx, row


def _add_registry_candidate(registry: Dict[str, DescriptionEvidence], key: str, desc: Any, *, source: str, weight: float = 1.0) -> None:
    description = clean_text(desc)
    if not key or not description or pollution_reason(description):
        return
    score = text_quality_score(description) * weight
    if score <= 0:
        return
    cur = registry.get(key)
    if cur is None:
        registry[key] = DescriptionEvidence(description, score, source, 1, False)
        return
    sim = similarity(cur.descricao, description)
    if sim >= 0.92:
        cur.occurrences += 1
        if len(description) > len(cur.descricao) or score > cur.score:
            cur.descricao = description
            cur.score = max(score, cur.score)
            cur.source = f"{cur.source}+{source}"
    elif score > cur.score + 0.8:
        registry[key] = DescriptionEvidence(description, score, source, 1, False)


def build_description_registry(orcamento: OrcamentoSintetico | None, comp: Composicoes | None) -> Dict[str, Dict[str, Any]]:
    registry: Dict[str, DescriptionEvidence] = {}
    if comp is not None:
        for collection, block_key, block in _iter_blocks(comp):
            for group, idx, line in _iter_lines(block):
                if is_sicro_bank(getattr(line, "banco", "")):
                    continue
                key = codebank(getattr(line, "codigo", ""), getattr(line, "banco", ""))
                _add_registry_candidate(registry, key, getattr(line, "descricao", ""), source=f"composition.{collection}.{block_key}.{group}{'' if idx is None else '.'+str(idx)}", weight=1.05 if group == "principal" else 1.0)
    if orcamento is not None:
        for item in _all_budget_items(getattr(orcamento, "itens_raiz", []) or []):
            if str(getattr(item, "tipo", "")).lower() != "item":
                continue
            key = codebank(getattr(item, "codigo", ""), getattr(item, "fonte", ""))
            _add_registry_candidate(registry, key, getattr(item, "especificacao", ""), source=f"budget.{getattr(item, 'item', '')}", weight=0.98)
    # Mark confirmed by repetition, high quality, or strong non-truncated complete text.
    out: Dict[str, Dict[str, Any]] = {}
    for key, ev in registry.items():
        ev.confirmed = ev.occurrences >= 2 or (ev.score >= 2.4 and len(ev.descricao) >= 45 and not is_truncated_text(ev.descricao))
        out[key] = ev.as_dict()
    return out


def _candidate_patch_decision(current: str, candidate: str, evidence: Dict[str, Any]) -> Dict[str, Any]:
    decision = {
        "before": current,
        "candidate": candidate,
        "decision": "rejected",
        "score": 0.0,
        "reasons": [],
        "evidence": evidence,
    }
    if not candidate:
        decision["reasons"].append("empty_candidate")
        return decision
    veto = pollution_reason(candidate)
    if veto:
        decision["reasons"].append(veto)
        return decision
    if current and similarity(current, candidate) >= 0.97:
        decision["reasons"].append("current_already_matches_confirmed_description")
        return decision
    if current and not is_truncated_text(current) and len(current) >= len(candidate) - 5:
        decision["reasons"].append("current_not_truncated_and_not_shorter")
        return decision
    sim = similarity(current, candidate) if current else 0.0
    prefix_ok = bool(current and norm_text(candidate).startswith(norm_text(current)))
    contains_ok = bool(current and norm_text(current) in norm_text(candidate))
    score = text_quality_score(candidate) + (2.0 if prefix_ok else 0.0) + (1.0 if contains_ok else 0.0) + (1.0 if is_truncated_text(current) else 0.0) + sim
    decision["score"] = round(score, 4)
    if score < 5.2:
        decision["reasons"].append("score_below_threshold")
        return decision
    decision.update({"decision": "applied", "after": candidate, "reasons": ["confirmed_description", "pollution_veto_passed", "score_passed"]})
    return decision


def apply_registry_recheck_to_compositions(comp: Composicoes, registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    metrics = {"rows_scanned": 0, "repairs_applied": 0, "repairs_rejected": 0, "confirmed_blocks": 0}
    repairs: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for collection, block_key, block in _iter_blocks(comp):
        if is_sicro_bank(getattr(getattr(block, "principal", None), "banco", "")):
            continue
        block_repairs: List[Dict[str, Any]] = []
        for group, idx, line in _iter_lines(block):
            metrics["rows_scanned"] += 1
            key = codebank(getattr(line, "codigo", ""), getattr(line, "banco", ""))
            ev = registry.get(key) or {}
            if not ev or not ev.get("confirmed"):
                continue
            current = clean_text(getattr(line, "descricao", ""))
            candidate = clean_text(ev.get("descricao"))
            decision = _candidate_patch_decision(current, candidate, {"codebank": key, "registry": {k: v for k, v in ev.items() if k != "descricao"}})
            decision.update({"collection": collection, "block": block_key, "row_group": group, "row_index": idx, "codebank": key})
            if decision["decision"] == "applied":
                line.descricao = candidate
                repairs.append(decision); block_repairs.append(decision); metrics["repairs_applied"] += 1
            else:
                rejected.append(decision); metrics["repairs_rejected"] += 1
                if "current_already_matches_confirmed_description" in decision.get("reasons", []):
                    metrics["confirmed_blocks"] += 1
        if block_repairs:
            details = dict(getattr(block, "detalhes", {}) or {})
            details.setdefault("broken_line_registry_recheck", {})
            details["broken_line_registry_recheck"].update({"version": VERSION, "repairs": block_repairs})
            block.detalhes = details
    return {"version": VERSION, "metrics": metrics, "repairs": repairs[:100], "rejected_repairs": rejected[:100]}


def apply_registry_recheck_to_budget(orcamento: OrcamentoSintetico, registry: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    metrics = {"items_scanned": 0, "repairs_applied": 0, "repairs_rejected": 0, "confirmed_blocks": 0}
    repairs: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for item in _all_budget_items(getattr(orcamento, "itens_raiz", []) or []):
        if str(getattr(item, "tipo", "")).lower() != "item":
            continue
        metrics["items_scanned"] += 1
        key = codebank(getattr(item, "codigo", ""), getattr(item, "fonte", ""))
        ev = registry.get(key) or {}
        if not ev or not ev.get("confirmed"):
            continue
        current = clean_text(getattr(item, "especificacao", ""))
        candidate = clean_text(ev.get("descricao"))
        decision = _candidate_patch_decision(current, candidate, {"codebank": key, "registry": {k: v for k, v in ev.items() if k != "descricao"}})
        decision.update({"item": getattr(item, "item", ""), "codigo": getattr(item, "codigo", ""), "banco": getattr(item, "fonte", ""), "codebank": key})
        if decision["decision"] == "applied":
            item.especificacao = candidate
            repairs.append(decision); metrics["repairs_applied"] += 1
        else:
            rejected.append(decision); metrics["repairs_rejected"] += 1
            if "current_already_matches_confirmed_description" in decision.get("reasons", []):
                metrics["confirmed_blocks"] += 1
    return {"version": VERSION, "metrics": metrics, "repairs": repairs[:100], "rejected_repairs": rejected[:100]}
