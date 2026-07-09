from __future__ import annotations

import io
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover - opcional no modo browser
    pdfplumber = None
from pypdf import PdfReader

from app.core.money import parse_ptbr_number
from app.core.numeric_fidelity import numeric_source
from app.core.pdf_session import PdfDocumentSession
from app.core.sanitizer import normalize_service_text
from app.core.context_markers import build_dynamic_markers
from app.core.base_rules import canonical_bank, detect_composition_label, get_bank_aliases, header_cfg, is_header_row, line_has_header_markers, norm_text, resolve_header_cells
from app.core.schemas import BlocoComposicao, Composicoes, LinhaComposicao, LinhaInsumo
from app.parser.sicro import extract_sicro_blocks_from_text, materialize_sicro_block
from app.parser.table_candidates import build_table_candidates
from app.parser.table_fusion import fuse_table_candidates
from app.parser.table_structure import pymupdf_tables_as_matrices
from app.parser.docling_column_map import DoclingColumnMap
from app.parser.description_guard import strip_noise_from_description
from app.parser.column_boundary_guard import clean_description_prefix, code_key, normalize_code_display, looks_like_code
from app.parser.sicro_section_patterns import SICRO_SECTION_REGEXES

TABLE_SETTINGS_LINES = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "intersection_tolerance": 5,
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 10,
    "text_tolerance": 2,
}
TABLE_SETTINGS_TEXT = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "intersection_tolerance": 5,
    "snap_tolerance": 3,
    "join_tolerance": 3,
    "edge_min_length": 10,
    "text_tolerance": 2,
}

def _known_banks(runtime: dict | None = None, config: dict | None = None) -> set[str]:
    """Return canonical bank names from runtime/config aliases."""
    if runtime and isinstance(runtime.get("banks"), dict) and runtime.get("banks"):
        return set(runtime["banks"].keys())
    return set(get_bank_aliases(config or {}).keys())

RE_NUM = re.compile(r"^\d[\d\.,]*$")
RE_ID_TABELA = re.compile(r"^\d+(?:\.\d+)*$")
RE_CODE_CAND = re.compile(r"^(?=.*\d)[0-9A-Z_]{3,}$")
RE_ITEM_HEADER_TEXT = re.compile(r"^(?P<item>\d+(?:\.\d+)*)\s+C[ÓO]DIGO(?:\s*BANCO|BANCO)", re.IGNORECASE)
RE_TABLE_HEADER_TEXT = re.compile(r"^C[ÓO]DIGO\s+BANCO\s+DESCRI(?:C[AÃ]O|Ç[AÃ]O)\s+UND\s+QUANT", re.IGNORECASE)
RE_ROW_START_TEXT = re.compile(r"^(?:COMPOSI(?:[ÇC][AÃ]O?)?|INSUMO)\s*", re.IGNORECASE)
RE_SPLIT_ROW_START_TEXT = re.compile(r"^(?:Composi(?:[çc][aã]o?)?|Insumo)\s*", re.IGNORECASE)
RE_EMBEDDED_ROW_CAND = re.compile(r"(?:Composi(?:[çc][aã]o?)?|Insumo)\s", re.IGNORECASE)
RE_TAIL_VALUES_TEXT = re.compile(
    r"(?P<und>[A-Za-z0-9/%²³]+)\s+(?P<quant>\d[\d\.,]*)\s+(?P<valor>\d[\d\.,]*)\s+(?P<total>\d[\d\.,]*)\s*$"
)

RE_TEXT_SECTION_HEADING = re.compile(
    r"^COMPOSI(?:[ÇC][AÃ]O|COES|ÇÕES|CAO|COES)?(?:\s+ANAL[IÍ]TICAS?|\s+PRINCIPAIS|\s+AUXILIARES?)\b",
    re.IGNORECASE,
)

_TAIL_UNIT_BLACKLIST = {"X", "LXAXC", "CXL", "AXC", "N", "NO", "NA", "DE", "DO", "DA"}


_DEFAULT_COMP_HEADER_ALIASES = {
    "item": ["ITEM"],
    "codigo": ["CÓDIGO", "CODIGO", "CÓD.", "COD.", "COD"],
    "banco": ["BANCO", "FONTE"],
    "descricao": ["DESCRIÇÃO", "DESCRICAO", "DESC.", "DESCR.", "ESPECIFICAÇÃO", "ESPECIFICACAO"],
    "tipo": ["TIPO"],
    "und": ["UND", "UNID", "UNIDADE", "UM", "U.M.", "UN"],
    "quant": ["QUANT", "QUANT.", "QTD", "QTD.", "QUANTIDADE"],
    "valor_unit": ["VALOR UNIT", "VALOR UNIT.", "VLR UNIT", "VALOR UNITÁRIO", "VALOR UNITARIO"],
    "total": ["TOTAL", "VALOR TOTAL"],
}

_COMP_LAYOUT_FIELDS = ["codigo", "banco", "descricao", "tipo", "und", "quant", "valor_unit", "total"]
_COMP_CANONICAL_BUCKET_KEYS = {
    "valor_unit": "valor",
}

_STANDARD_LAYOUT_MODELS: Dict[str, Dict[str, Any]] = {
    "sinapi_padrao": {
        "name": "sinapi_padrao",
        "regime": "sinapi_like",
        "columns": ["codigo", "banco", "descricao", "tipo", "und", "quant", "valor_unit", "total"],
        "tipo_expected": True,
        "sicro": False,
    },
    "orse_proprio_padrao": {
        "name": "orse_proprio_padrao",
        "regime": "orse_like",
        "columns": ["codigo", "banco", "descricao", "tipo", "und", "quant", "valor_unit", "total"],
        "tipo_expected": True,
        "sicro": False,
    },
    "sicro_generico": {
        "name": "sicro_generico",
        "regime": "sicro_like",
        "columns": ["codigo", "banco", "descricao", "und", "quant", "valor_unit", "total"],
        "tipo_expected": False,
        "sicro": True,
    },
    "misto_padrao": {
        "name": "misto_padrao",
        "regime": "misto",
        "columns": ["codigo", "banco", "descricao", "tipo", "und", "quant", "valor_unit", "total"],
        "tipo_expected": True,
        "sicro": False,
    },
}

_SICRO_SECTION_REGEXES = SICRO_SECTION_REGEXES


def _runtime_rules(config: dict | None) -> dict:
    return {
        "config": config or {},
        "banks": get_bank_aliases(config or {}),
        "header_cfg": header_cfg(
            config or {},
            key="composition_table_headers",
            default_aliases=_DEFAULT_COMP_HEADER_ALIASES,
            default_required=["codigo", "banco", "descricao"],
            default_similarity=0.82,
        ),
        "footer_markers": [norm_text(x) for x in ((config or {}).get("composition_footer_markers") or ["MO sem", "MO com LS", "Valor com BDI"])],
    }

def _is_fast_profile(config: dict | None) -> bool:
    performance_cfg = (config or {}).get("performance") or {}
    profile = str(performance_cfg.get("profile") or "").strip().lower()
    return profile in {"browser_fast", "fast"}


def _include_tipo_in_final_json(config: dict | None = None, context: dict | None = None) -> bool:
    return DoclingColumnMap.include_tipo_from_options(config=config, context=context)


def _structural_nature(kind: str = "") -> str:
    """Normalize internal row kind into the public natureza field.

    v61 hotfix: previous versions called this helper but did not define it,
    which broke the composition stage at runtime.
    """
    k = _clean(kind).upper()
    if not k:
        return ""
    if "INSUMO" in k:
        return "Insumo"
    if "AUX" in k:
        return "Composição Auxiliar"
    if "COMPOS" in k or "PRINC" in k:
        return "Composição"
    return _clean(kind).title()


def _sanitize_tipo(raw_tipo: str, bank: str = "") -> str:
    return _normalize_output_tipo(raw_tipo, bank=bank)


def _normalize_output_tipo(raw_tipo: str, bank: str = "") -> str:
    tipo = _clean(raw_tipo)
    if not tipo:
        return ""
    # SICRO sections use their own structure; tipo is not a domain field there.
    if _canon_bank(bank or "") == "SICRO":
        return ""
    if tipo.upper() in {"TIPO", "-", "—"}:
        return ""
    if norm_text(tipo) in {"composicao", "composicao auxiliar", "insumo"}:
        return ""
    tipo = re.sub(r"(?i)\s+MO\s+sem\s+.*$", "", tipo).strip()
    tipo = re.sub(r"(?i)\s+MO\s+com\s+LS.*$", "", tipo).strip()
    tipo = re.sub(r"(?i)\s+LS\s*=>.*$", "", tipo).strip()
    tipo = re.sub(r"(?i)\s+Valor\s+(?:com|sem)\s+BDI.*$", "", tipo).strip()
    if not tipo:
        return ""
    if _looks_like_unit_token(tipo):
        return ""
    return normalize_service_text(tipo.strip(" -,:;"))


def _finalize_output_description(descricao: str, *, code: str = "", bank: str = "") -> str:
    return _sanitize_description(str(descricao or ""), code=str(code or ""), bank=str(bank or ""), dynamic_markers=None)


def _finalize_output_line(line: LinhaComposicao | LinhaInsumo, *, include_tipo: bool | None = None) -> LinhaComposicao | LinhaInsumo:
    """Final guard before JSON serialization.

    Keeps codigo visible as in PDF, strips leaked codigo/banco from descricao,
    and hides tipo unless the output contract explicitly asks for it.
    """
    line.codigo = _normalize_code_candidate(str(getattr(line, "codigo", "") or ""))
    line.banco = _canon_bank(str(getattr(line, "banco", "") or ""))
    line.banco_coluna = _canon_bank(str(getattr(line, "banco_coluna", "") or line.banco or ""))
    line.descricao = _finalize_output_description(str(getattr(line, "descricao", "") or ""), code=line.codigo, bank=line.banco)
    if include_tipo is False:
        line.tipo = ""
        line.tipo_status = str(getattr(line, "tipo_status", "") or "excluded_by_output_contract")
    else:
        line.tipo = _normalize_output_tipo(str(getattr(line, "tipo", "") or ""), bank=line.banco)
        # Em modo automático (include_tipo=None), evita vazamento de classe de linha
        # na linha principal. Quando include_tipo=True é explícito, preserva o valor.
        if include_tipo is None and norm_text(str(getattr(line, "natureza", "") or "")) == "composicao" and norm_text(line.tipo) in {"mao de obra", "material", "equipamento", "servico"}:
            line.tipo = ""
    return line


def _resolve_text_fallback_mode(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("composition_text_fallback_mode") or "").strip().lower()
    if explicit in {"all_pages", "pages_without_tables"}:
        return explicit
    return "pages_without_tables" if _is_fast_profile(config) else "all_pages"


def _resolve_table_extraction_strategy(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("composition_table_extraction_strategy") or "").strip().lower()
    if explicit in {"adaptive", "all_candidates"}:
        return explicit
    return "adaptive" if _is_fast_profile(config) else "all_candidates"


def _resolve_table_probe_limit(config: dict | None) -> int:
    performance_cfg = (config or {}).get("performance") or {}
    try:
        explicit = int(performance_cfg.get("composition_table_probe_limit") or 0)
    except Exception:
        explicit = 0
    if explicit > 0:
        return explicit
    return 8 if _is_fast_profile(config) else 12


def _final_refinement_only(config: dict | None) -> bool:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = performance_cfg.get("composition_finalize_text_only")
    if explicit is None:
        return True
    return bool(explicit)


def _resolve_preclassification_neighbor_buffer(config: dict | None) -> int:
    performance_cfg = (config or {}).get("performance") or {}
    try:
        explicit = int(performance_cfg.get("composition_preclassification_neighbor_buffer") or 0)
    except Exception:
        explicit = 0
    return max(0, explicit if explicit else 1)


def _resolve_interval_processing_mode(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("composition_interval_processing_mode") or "").strip().lower()
    if explicit in {"layered", "uniform"}:
        return explicit
    return "layered" if _is_fast_profile(config) else "uniform"


def _resolve_tipo_recovery_mode(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("composition_tipo_recovery_mode") or "").strip().lower()
    if explicit in {"on_demand", "eager", "disabled", "api_only"}:
        return explicit
    return "on_demand" if _is_fast_profile(config) else "eager"


def _resolve_compact_debug(config: dict | None) -> bool:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = performance_cfg.get("composition_compact_debug")
    if explicit is None:
        return _is_fast_profile(config)
    return bool(explicit)


def _resolve_layout_template_strategy(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("composition_layout_template_strategy") or "").strip().lower()
    if explicit in {"standard_first", "local_only"}:
        return explicit
    return "standard_first"


def _resolve_sicro_template_mode(config: dict | None) -> str:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = str(performance_cfg.get("composition_sicro_template_mode") or "").strip().lower()
    if explicit in {"per_section", "uniform"}:
        return explicit
    return "per_section"


def _resolve_generic_text_include_pure_sicro_pages(config: dict | None) -> bool:
    performance_cfg = (config or {}).get("performance") or {}
    explicit = performance_cfg.get("composition_generic_text_include_pure_sicro_pages")
    if explicit is None:
        return not _is_fast_profile(config)
    return bool(explicit)


def _resolve_text_candidate_min_score(config: dict | None) -> int:
    performance_cfg = (config or {}).get("performance") or {}
    try:
        explicit = int(performance_cfg.get("composition_text_candidate_min_score") or 0)
    except Exception:
        explicit = 0
    if explicit > 0:
        return explicit
    return 5 if _is_fast_profile(config) else 3


def _resolve_text_candidate_neighbor_buffer(config: dict | None) -> int:
    performance_cfg = (config or {}).get("performance") or {}
    try:
        explicit = int(performance_cfg.get("composition_text_candidate_neighbor_buffer") or 0)
    except Exception:
        explicit = 0
    if explicit > 0:
        return explicit
    return 0 if _is_fast_profile(config) else 1


def _effective_matching_shortlist_cap(base_cap: int, *, fast_mode: bool, total_refs: int, candidate_count: int) -> int:
    cap = max(0, int(base_cap or 0))
    if not cap:
        return 0
    if not fast_mode:
        return cap
    if total_refs >= 140 or candidate_count >= 220:
        return min(cap, 8)
    if total_refs >= 90 or candidate_count >= 140:
        return min(cap, 10)
    if total_refs >= 45 or candidate_count >= 80:
        return min(cap, 12)
    return cap


def _select_text_fallback_pages(all_page_numbers: List[int], pages_with_comp_tables: set[int], *, mode: str, pages_with_open_block: set[int] | None = None) -> List[int]:
    forced_pages = set(pages_with_open_block or [])
    if mode == "pages_without_tables":
        selected = [page_no for page_no in all_page_numbers if page_no not in pages_with_comp_tables or page_no in forced_pages]
        return selected or list(all_page_numbers)
    return list(all_page_numbers)


COMPOSITION_NOISE_PATTERNS = [
    r"\bVALOR\s+COM\s+BDI\b",
    r"\bEQUIPAMENTO\s+PARA\s+AQUISI[CÇ][AÃ]O\s+PERMANENTE\b",
    r"\bLIVRO\s+SINAPI\b",
    r"\bLIVRO\b",
    r"\bC[ÁA]LCULOS\s+E\s+PAR[ÂA]METROS\b",
    r"\bC[ÁA]LCULOS\s+E\b",
    r"\bPAR[ÂA]METROS\b",
    r"\bC[ÓO]DIGO\s+BANCO\s+DESCRI[CÇ][AÃ]O\s+UND\s+QUANT\.?\s+VALOR\s+UNIT\s+TOTAL\b",
    r"\bUND\s+QUANT\.?\s+VALOR\s+UNIT\s+TOTAL\b",
    r"\bMO\s+SEM\b",
    r"\bLS\s*=>\b",
    r"\bMO\s+COM\s+LS\b",
    r"\bDETALHAMENTO\s+DE\s+C[ÁA]LCULO\b",
    r"\bOBJETO:\b",
    r"\bMUNIC[ÍI]PIO:\b",
    r"\bENDERE[ÇC]O:\b",
    r"\bDATA:\b",
    r"\bENC\.?\s+SOCIAIS\b",
    r"\bANEXO\s+\d\b",
    r"#ENC\.\s*SOCIAIS",
    r"\bASSINATURA\b",
    r"\bRESPONS[ÁA]VEL\s+T[ÉE]CNICO\b",
    r"\bCREA\b",
]
RE_TAIL_VALUES_ANYWHERE = re.compile(r"\s+[A-Za-z/%²³0-9]{1,12}\s+\d[\d\.,]*\s+\d[\d\.,]*\s+\d[\d\.,]*\s*$")

STRUCTURAL_LABEL_PREFIXES = tuple(sorted({
    "OCOMPOSICAOAUXILIAR",
    "COMPOSICAOAUXILIAR",
    "OCOMPOSICAO",
    "COMPOSICAO",
    "OCOMPOSI",
    "COMPOSI",
    "OAUXILIAR",
    "AUXILIAR",
    "OINSUMO",
    "INSUMO",
}, key=len, reverse=True))


def _strip_structural_label_prefixes(value: str) -> str:
    cand = re.sub(r"[^0-9A-Z_]", "", _clean(value).upper())
    previous = None
    while cand and cand != previous:
        previous = cand
        for prefix in STRUCTURAL_LABEL_PREFIXES:
            if cand.startswith(prefix):
                cand = cand[len(prefix):]
                break
    return cand


def _normalize_code_candidate(raw: str) -> str:
    # v60.5.3: preserve the code as it appears in the PDF for output fields.
    # Punctuation such as /, ., hyphen and meaningful spaces must not be removed.
    return normalize_code_display(raw)


def _normalize_code_key_part(raw: str) -> str:
    return code_key(raw)


def _normalize_ref_key(code: str, bank: str) -> str:
    code_part = _normalize_code_key_part(code)
    bank = _canon_bank(bank)
    return f"{code_part}|{bank}" if code_part and bank else ""


def _make_recovery_key(item: str, bank: str) -> str:
    item = _clean(item)
    bank = _canon_bank(bank)
    return f"__ITEM__{item}|{bank}" if item and bank else ""


def _is_recovery_key(key: str) -> bool:
    return str(key or "").startswith("__ITEM__")


def _extract_joined_code(tokens: List[str], end_idx: int) -> str:
    candidates: List[str] = []
    start = max(0, end_idx - 3)
    skip_tokens = {"O", "AUXILIAR", "COMPOSICAO", "COMPOSIÇÃO", "INSUMO"}
    for i in range(start, end_idx):
        part_tokens = [t for t in tokens[i:end_idx] if t and t not in skip_tokens]
        if not part_tokens:
            continue
        raw = _normalize_code_candidate(''.join(part_tokens))
        if raw:
            candidates.append(raw)
    candidates.sort(key=len, reverse=True)
    for cand in candidates:
        if _is_strong_code_candidate(cand):
            return cand
    return ""
def _strip_leading_structural_marker(text: str) -> str:
    s = _clean(text)
    if not s:
        return ""
    s = re.sub(r"(?i)^o\s+(?=(?:Composi[çc][aã]o?|Auxiliar|Insumo)\b)", "", s).strip()
    s = re.sub(r"(?i)^Composi[çc][aã]o?\s+Auxiliar\b", "", s).strip()
    s = re.sub(r"(?i)^Composi[çc][aã]o?\b", "", s).strip()
    s = re.sub(r"(?i)^Auxiliar\b(?!\s+de\b)", "", s).strip()
    s = re.sub(r"(?i)^Insumo\b", "", s).strip()
    return s


def _sanitize_description(text: str, code: str = "", bank: str = "", dynamic_markers: List[str] | None = None) -> str:
    s = _strip_leading_structural_marker(text)
    if not s:
        return ""
    split = clean_description_prefix(s, code=code, bank=bank)
    if split.get("changed"):
        s = str(split.get("descricao") or "")
    if code:
        s = re.sub(rf"(?i)^o?\s*{re.escape(code)}\b", "", s).strip()
        parts = s.split()
        if parts and code_key(parts[0]) == code_key(code):
            s = s[len(parts[0]):].strip()
    if bank:
        s = re.sub(rf"(?i)^o?\s*{re.escape(bank)}\b", "", s).strip()
        m_bank_prefix = re.match(rf"(?i)^o?\s*[0-9A-Z_./ -]{{0,40}}{re.escape(bank)}\b\s*", s)
        if m_bank_prefix:
            s = s[m_bank_prefix.end():].strip()
    s = re.sub(r"\s+", " ", s).strip()

    while True:
        m_tail = RE_TAIL_VALUES_ANYWHERE.search(s)
        if not m_tail:
            break
        s = s[: m_tail.start()].rstrip(" -,:;")

    cut_idx = None
    for pat in COMPOSITION_NOISE_PATTERNS:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            cut_idx = m.start() if cut_idx is None else min(cut_idx, m.start())
    for marker in (dynamic_markers or []):
        idx = s.find(marker)
        if idx != -1:
            cut_idx = idx if cut_idx is None else min(cut_idx, idx)
    if cut_idx is not None:
        s = s[:cut_idx].rstrip(" -,:;")

    s = re.sub(r"\s+\d[\d\.,]*\s+LS\s*=>.*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+\d[\d\.,]*\s+\d[\d\.,]*\s+\d[\d\.,]*$", "", s)
    s = normalize_service_text(re.sub(r"\s+", " ", s).strip(" -,:;"))
    return s


def _tipo_candidate_key(codigo: str, banco: str) -> str:
    return _normalize_ref_key(_normalize_code_candidate(codigo), _canon_bank(banco))


def _tipo_candidate_score(tipo: str) -> tuple[int, int]:
    s = _normalize_output_tipo(tipo)
    if not s:
        return (-1, -1)
    score = 0
    if " " in s:
        score += 3
    if re.search(r"[A-Za-zÀ-ÿ]", s):
        score += 2
    if re.search(r"\d", s):
        score += 1
    return (score, len(s))


def _register_tipo_candidate(tipo_candidates: Dict[str, str], codigo: str, banco: str, raw_tipo: str) -> None:
    key = _tipo_candidate_key(codigo, banco)
    if not key:
        return
    tipo = _normalize_output_tipo(raw_tipo, bank=banco)
    if not tipo:
        return
    current = str(tipo_candidates.get(key) or "")
    if not current or _tipo_candidate_score(tipo) > _tipo_candidate_score(current):
        tipo_candidates[key] = tipo


def _strip_embedded_tipo_from_description(descricao: str, tipo: str) -> str:
    desc = _clean(descricao)
    tipo = _clean(tipo)
    if not desc or not tipo:
        return desc
    escaped = re.escape(tipo)
    patterns = [
        rf"(?i)\bTIPO\s*[:\-]?\s*{escaped}\s*$",
        rf"(?i)\b{escaped}\s*$",
    ]
    trimmed = desc
    for pat in patterns:
        new = re.sub(pat, "", trimmed).rstrip(" -,:;")
        if new != trimmed and new:
            trimmed = new
            break
    return trimmed


def _backfill_line_tipo(line: LinhaComposicao | LinhaInsumo, tipo_candidates: Dict[str, str]) -> LinhaComposicao | LinhaInsumo:
    if _canon_bank(getattr(line, "banco", "") or "") == "SICRO":
        line.tipo = ""
        return line
    if _clean(getattr(line, "tipo", "") or ""):
        line.tipo = _normalize_output_tipo(str(line.tipo or ""), bank=str(getattr(line, "banco", "") or ""))
        return line
    key = _tipo_candidate_key(str(getattr(line, "codigo", "") or ""), str(getattr(line, "banco", "") or ""))
    candidate = str(tipo_candidates.get(key) or "")
    if not candidate:
        return line
    line.tipo = candidate
    line.descricao = _strip_embedded_tipo_from_description(str(getattr(line, "descricao", "") or ""), candidate)
    return line


def _backfill_missing_tipos_in_blocks(
    blocks: Dict[str, Any],
    orphan_aux: Dict[str, LinhaComposicao],
    tipo_candidates: Dict[str, str],
) -> None:
    if not tipo_candidates:
        return
    for block in blocks.values():
        principal = getattr(block, "principal", None)
        if principal is not None:
            block.principal = _backfill_line_tipo(principal, tipo_candidates)
        aux_attr = "auxiliares" if hasattr(block, "auxiliares") else "composicoes_auxiliares"
        aux_list = list(getattr(block, aux_attr, []) or [])
        setattr(block, aux_attr, [_backfill_line_tipo(line, tipo_candidates) for line in aux_list])
        ins_list = list(getattr(block, "insumos", []) or [])
        block.insumos = [LinhaInsumo(**_backfill_line_tipo(LinhaInsumo(**line.model_dump()), tipo_candidates).model_dump()) for line in ins_list]
    for key, line in list(orphan_aux.items()):
        orphan_aux[key] = _backfill_line_tipo(line, tipo_candidates)


def _lightweight_clean_description(text: str, code: str = "", bank: str = "") -> str:
    s = _strip_leading_structural_marker(text)
    if not s:
        return ""
    if code:
        s = re.sub(rf"(?i)^o?\s*{re.escape(code)}\b", "", s).strip()
    if bank:
        s = re.sub(rf"(?i)^o?\s*{re.escape(bank)}\b", "", s).strip()
    return re.sub(r"\s+", " ", s).strip(" -,:;")

@dataclass
class RawBlock:
    item: str = ""
    key: str = ""
    principal: Optional[LinhaComposicao] = None
    auxiliares: List[LinhaComposicao] = field(default_factory=list)
    insumos: List[LinhaInsumo] = field(default_factory=list)
    page: int = 0
    page_start: int = 0
    page_end: int = 0
    pages_seen: List[int] = field(default_factory=list)
    closure_reason: str = ""
    detalhes: Dict[str, Any] = field(default_factory=dict)




def _touch_block_page(block: RawBlock | None, page_no: int, *, source: str | None = None) -> None:
    if block is None or not page_no:
        return
    if not block.page:
        block.page = int(page_no)
    if not block.page_start or page_no < block.page_start:
        block.page_start = int(page_no)
    if not block.page_end or page_no > block.page_end:
        block.page_end = int(page_no)
    if int(page_no) not in block.pages_seen:
        block.pages_seen.append(int(page_no))
        block.pages_seen.sort()
    if source:
        detalhes = dict(block.detalhes or {})
        sources = list(detalhes.get("origens_extracao") or [])
        if source not in sources:
            sources.append(source)
        detalhes["origens_extracao"] = sources
        block.detalhes = detalhes


def _note_block_recovery(block: RawBlock | None, message: str) -> None:
    if block is None or not message:
        return
    detalhes = dict(block.detalhes or {})
    attempts = list(detalhes.get("tentativas_recuperacao") or [])
    if message not in attempts:
        attempts.append(message)
    detalhes["tentativas_recuperacao"] = attempts
    block.detalhes = detalhes


def _mark_block_closure(block: RawBlock | None, reason: str, *, page_no: int | None = None) -> None:
    if block is None:
        return
    if page_no:
        _touch_block_page(block, int(page_no))
    if reason and not block.closure_reason:
        block.closure_reason = str(reason)
    detalhes = dict(block.detalhes or {})
    if reason and not detalhes.get("motivo_fechamento"):
        detalhes["motivo_fechamento"] = str(reason)
    detalhes["pagina_inicio"] = block.page_start or detalhes.get("pagina_inicio")
    detalhes["pagina_fim"] = block.page_end or detalhes.get("pagina_fim")
    detalhes["paginas"] = list(block.pages_seen or detalhes.get("paginas") or [])
    block.detalhes = detalhes

# -------------------------------
# limpeza / classificação
# -------------------------------
def _clean(txt: Any) -> str:
    if txt is None:
        return ""
    return str(txt).replace("\n", " ").replace("\xa0", " ").strip()


def _norm(txt: Any) -> str:
    return re.sub(r"\s+", " ", _clean(txt)).upper()


def _normalized_upper(txt: Any) -> str:
    return _norm(normalize_service_text(str(txt or "")))


def _is_item_id(value: str) -> bool:
    return bool(RE_ID_TABELA.fullmatch(_clean(value)))


def _table_quality_score(table: List[List[str]]) -> tuple[int, int, int]:
    """
    Heurística leve e reutilizável para priorizar tabelas mais confiáveis.

    Preferimos tabelas que:
    - tenham mais linhas estruturais reconhecíveis;
    - tenham menos linhas muito fragmentadas;
    - exponham colunas explícitas de código/banco/descrição.
    """
    structural_rows = 0
    fragmented_rows = 0
    explicit_columns = 0

    for row in table[:120]:
        if not row:
            continue
        cells = [_clean(c) for c in row if c is not None]
        if not any(cells):
            continue
        if _looks_like_header(cells):
            explicit_columns += 1
        kind = _row_kind(cells)
        if kind:
            structural_rows += 1
        non_empty = [c for c in cells if c]
        if len(non_empty) >= 4:
            short_cells = sum(1 for c in non_empty[:6] if len(c) <= 3)
            if short_cells >= 3:
                fragmented_rows += 1

    return structural_rows, explicit_columns, -fragmented_rows


def _detect_sicro_sections_in_text(page_text: str) -> List[str]:
    sections: List[str] = []
    lines = [_clean(x) for x in str(page_text or "").splitlines() if _clean(x)]
    for section, patterns in _SICRO_SECTION_REGEXES.items():
        for line in lines[:160]:
            if any(pattern.search(line) for pattern in patterns):
                sections.append(section)
                break
    return sorted(set(sections))


def _page_regime_from_signals(up: str, *, sicro_candidate: bool, non_sicro_bank_hits: int, tipo_candidate: bool) -> str:
    if sicro_candidate and non_sicro_bank_hits <= 0:
        return "sicro_like"
    if sicro_candidate and non_sicro_bank_hits > 0:
        return "misto"
    if "ORSE" in up or "DETALHAMENTO DE CALCULO ORSE" in up or "DETALHAMENTO DE CÁLCULO ORSE" in up or "PROPRIO" in up or "PRÓPRIO" in up:
        return "orse_like"
    if "SINAPI" in up or "LIVRO SINAPI" in up or tipo_candidate:
        return "sinapi_like"
    return "generic"


def _predefined_layout_model(regime: str) -> Dict[str, Any]:
    if regime == "sicro_like":
        return dict(_STANDARD_LAYOUT_MODELS["sicro_generico"])
    if regime == "orse_like":
        return dict(_STANDARD_LAYOUT_MODELS["orse_proprio_padrao"])
    if regime == "misto":
        return dict(_STANDARD_LAYOUT_MODELS["misto_padrao"])
    return dict(_STANDARD_LAYOUT_MODELS["sinapi_padrao"])


def _build_interval_layout_templates(page_texts: List[str], all_page_numbers: List[int], page_profiles: dict[int, dict[str, Any]], *, config: dict | None = None) -> dict[str, Any]:
    strategy = _resolve_layout_template_strategy(config)
    sicro_mode = _resolve_sicro_template_mode(config)
    blocks: List[dict[str, Any]] = []
    blocks_by_id: dict[str, dict[str, Any]] = {}
    pure_sicro_pages: List[int] = []
    dedicated_sicro_pages: List[int] = []
    metrics: dict[str, Any] = {
        "standard_model_pages": 0,
        "dedicated_sicro_pages": 0,
        "block_count": 0,
        "sicro_block_count": 0,
        "standard_block_hits": 0,
        "standard_block_failures": 0,
        "local_template_hits": 0,
        "local_template_creations": 0,
        "heavy_block_parses": 0,
        "heavy_block_successes": 0,
        "sicro_section_standard_hits": 0,
        "sicro_section_template_hits": 0,
        "tipo_recovery_block_hits": 0,
        "page_reparse_count": 0,
        "sicro_doc_profile_locked": 0,
        "sicro_doc_profile_hits": 0,
    }
    current: dict[str, Any] | None = None
    block_index = 0
    doc_sicro_templates: dict[str, dict[str, Any]] = {}
    for idx, page_no in enumerate(all_page_numbers):
        profile = dict(page_profiles.get(page_no) or {})
        regime = str(profile.get("regime") or "generic")
        model = _predefined_layout_model(regime)
        pure_sicro = bool(profile.get("pure_sicro"))
        if pure_sicro:
            pure_sicro_pages.append(page_no)
        if current is None or current.get("regime") != regime or (regime == "misto" and len(current.get("page_numbers") or []) >= 4):
            block_index += 1
            current = {
                "id": f"block_{block_index}",
                "regime": regime,
                "model_name": model.get("name"),
                "template_source": "standard" if strategy == "standard_first" else "local",
                "page_numbers": [],
                "tipo_expected": bool(model.get("tipo_expected")),
                "tipo_layout": None,
                "sicro_templates": {},
                "doc_sicro_templates": {},
                "dedicated_sicro_only": False,
            }
            blocks.append(current)
            blocks_by_id[current["id"]] = current
        current["page_numbers"].append(page_no)
        sections = list(profile.get("sicro_sections") or [])
        if regime == "sicro_like" and sicro_mode == "per_section":
            for section in sections:
                template = {
                    "section": section,
                    "first_page": page_no,
                    "template_source": "learned_first_occurrence",
                }
                current["sicro_templates"].setdefault(section, template)
                doc_sicro_templates.setdefault(section, dict(template))
        profile.update({
            "block_id": current["id"],
            "model_name": current.get("model_name"),
            "template_source": current.get("template_source"),
            "tipo_expected": bool(current.get("tipo_expected")) and regime != "sicro_like",
            "known_sicro_templates": sorted((current.get("sicro_templates") or {}).keys()),
        })
        page_profiles[page_no] = profile

    doc_sicro_profile_locked = bool(doc_sicro_templates)
    if doc_sicro_profile_locked:
        metrics["sicro_doc_profile_locked"] = 1

    for block in blocks:
        pages = list(block.get("page_numbers") or [])
        regime = str(block.get("regime") or "generic")
        if regime == "sicro_like" and doc_sicro_profile_locked:
            block["doc_sicro_templates"] = {sec: dict(meta) for sec, meta in doc_sicro_templates.items()}
        else:
            block["doc_sicro_templates"] = {}
        dedicated_pages = [
            page_no for page_no in pages
            if bool((page_profiles.get(page_no) or {}).get("dedicated_sicro"))
        ]
        if regime == "sicro_like" and dedicated_pages:
            block["dedicated_sicro_only"] = True
            block["dedicated_sicro_pages"] = list(dedicated_pages)
            dedicated_sicro_pages.extend(dedicated_pages)
            metrics["sicro_block_count"] += 1
        else:
            block["dedicated_sicro_pages"] = []
        if str(block.get("template_source") or "") == "standard":
            metrics["standard_model_pages"] += len(pages)
        if regime == "sicro_like":
            known_sections = sorted(set((block.get("sicro_templates") or {}).keys()) | set((block.get("doc_sicro_templates") or {}).keys()))
            if known_sections:
                metrics["sicro_section_standard_hits"] += len(known_sections)
                if doc_sicro_profile_locked:
                    metrics["sicro_doc_profile_hits"] += len(pages)
        metrics["block_count"] += 1

    for page_no in all_page_numbers:
        profile = dict(page_profiles.get(page_no) or {})
        block_id = str(profile.get("block_id") or "")
        block = blocks_by_id.get(block_id) if block_id else None
        doc_templates = (block.get("doc_sicro_templates") or {}) if isinstance(block, dict) else {}
        local_templates = (block.get("sicro_templates") or {}) if isinstance(block, dict) else {}
        known = sorted(set(local_templates.keys()) | set(doc_templates.keys()))
        if known:
            profile["known_sicro_templates"] = known
            profile["doc_sicro_profile_locked"] = bool(doc_templates)
            if doc_templates:
                profile["doc_sicro_template_sections"] = sorted(doc_templates.keys())
        page_profiles[page_no] = profile

    dedicated_sicro_pages = [page_no for page_no in all_page_numbers if page_no in set(dedicated_sicro_pages)]
    metrics["dedicated_sicro_pages"] = len(dedicated_sicro_pages)
    return {
        "blocks": blocks,
        "blocks_by_id": blocks_by_id,
        "pure_sicro_pages": pure_sicro_pages,
        "dedicated_sicro_pages": dedicated_sicro_pages,
        "doc_sicro_profile_locked": doc_sicro_profile_locked,
        "doc_sicro_templates": {sec: dict(meta) for sec, meta in doc_sicro_templates.items()},
        "metrics": metrics,
    }


def _page_likely_contains_composition_data(page_text: str, runtime: dict | None = None) -> bool:
    up = _norm(page_text)
    if not up:
        return False
    strong_markers = [
        "COMPOSI",
        "INSUMO",
        "VALOR COM BDI",
        "MO SEM",
        "CODIGO BANCO DESCRI",
        "CÓDIGO BANCO DESCRI",
        "SICRO",
    ]
    if any(marker in up for marker in strong_markers):
        return True
    banks = _known_banks(runtime)
    return sum(1 for bank in banks if bank and bank in up) >= 2 and ("TOTAL" in up or "QUANT" in up)


def _page_composition_signals(page_text: str, runtime: dict | None = None, config: dict | None = None) -> dict[str, Any]:
    up = _norm(page_text)
    if not up:
        return {
            "score": 0,
            "contains_data": False,
            "table_candidate": False,
            "text_candidate": False,
            "sicro_candidate": False,
            "strong": False,
            "header_hits": 0,
            "item_header_hits": 0,
            "structural_hits": 0,
            "tipo_candidate": False,
            "tipo_header_hits": 0,
            "tipo_value_hits": 0,
            "regime": "generic",
            "non_sicro_bank_hits": 0,
            "pure_sicro": False,
            "sicro_sections": [],
        }

    header_hits = sum(up.count(marker) for marker in ["CODIGO BANCO DESCRI", "CÓDIGO BANCO DESCRI", "VALOR UNIT TOTAL", "UND QUANT"])
    item_header_hits = len(re.findall(r"\b\d+(?:\.\d+)*\s+C[ÓO]DIGO\s+BANCO\b", up))
    structural_hits = up.count("COMPOSI") + up.count("INSUMO")
    cost_footer_hits = up.count("VALOR COM BDI") + up.count("MO SEM")
    sicro_hits = up.count("SICRO") + up.count("DNIT")
    quant_total_hits = up.count("QUANT") + up.count("TOTAL")
    banks = _known_banks(runtime)
    bank_hits = sum(1 for bank in banks if bank and bank in up)
    non_sicro_banks = {bank for bank in banks if bank not in {"SICRO", "DNIT"}}
    non_sicro_bank_hits = sum(1 for bank in non_sicro_banks if bank and bank in up)

    tipo_header_hits = len(re.findall(r"\bTIPO\b", up))
    tipo_value_markers = [
        "MATERIAL",
        "PROVISORIOS",
        "PROVISÓRIOS",
        "MAO DE OBRA",
        "MÃO DE OBRA",
        "SERVICOS",
        "SERVIÇOS",
        "LIVRO SINAPI",
        "DETALHAMENTO DE CALCULO ORSE",
        "DETALHAMENTO DE CÁLCULO ORSE",
    ]
    tipo_value_hits = sum(up.count(marker) for marker in tipo_value_markers)
    tipo_candidate = bool(tipo_header_hits or tipo_value_hits >= 2 or "LIVRO SINAPI" in up)
    text_min_score = _resolve_text_candidate_min_score(config)

    score = 0
    score += header_hits * 8
    score += item_header_hits * 7
    score += min(structural_hits, 8) * 3
    score += min(cost_footer_hits, 4) * 2
    score += min(tipo_header_hits, 3) * 2
    score += min(tipo_value_hits, 4)
    if bank_hits >= 2 and quant_total_hits > 0:
        score += 3
    if sicro_hits > 0:
        score += 2

    contains_data = score >= 3 or _page_likely_contains_composition_data(page_text, runtime=runtime)
    table_candidate = bool(header_hits or item_header_hits or (structural_hits >= 3 and quant_total_hits >= 2))
    text_candidate = bool(
        header_hits
        or item_header_hits
        or structural_hits >= 2
        or cost_footer_hits >= 1
        or score >= text_min_score
        or (tipo_header_hits >= 1)
        or (tipo_value_hits >= 2 and structural_hits >= 1)
        or (bank_hits >= 2 and quant_total_hits > 0 and structural_hits >= 1)
    )
    strong = bool(header_hits or item_header_hits or structural_hits >= 3 or score >= 10)
    sicro_candidate = bool(sicro_hits and (structural_hits or header_hits or item_header_hits or cost_footer_hits))
    regime = _page_regime_from_signals(up, sicro_candidate=sicro_candidate, non_sicro_bank_hits=non_sicro_bank_hits, tipo_candidate=tipo_candidate)
    return {
        "score": score,
        "contains_data": contains_data,
        "table_candidate": table_candidate,
        "text_candidate": text_candidate,
        "sicro_candidate": sicro_candidate,
        "strong": strong,
        "header_hits": header_hits,
        "item_header_hits": item_header_hits,
        "structural_hits": structural_hits,
        "tipo_candidate": tipo_candidate,
        "tipo_header_hits": tipo_header_hits,
        "tipo_value_hits": tipo_value_hits,
        "regime": regime,
        "non_sicro_bank_hits": non_sicro_bank_hits,
        "pure_sicro": bool(regime == "sicro_like" and non_sicro_bank_hits <= 0),
        "sicro_sections": _detect_sicro_sections_in_text(page_text) if sicro_candidate else [],
    }


def _buffer_adjacent_pages(selected: List[int], ordered_pages: List[int], *, radius: int = 1) -> List[int]:
    if not selected or radius <= 0:
        return list(selected)
    page_index = {page_no: idx for idx, page_no in enumerate(ordered_pages)}
    out: set[int] = set(selected)
    for page_no in list(selected):
        idx = page_index.get(page_no)
        if idx is None:
            continue
        for offset in range(1, radius + 1):
            prev_idx = idx - offset
            next_idx = idx + offset
            if prev_idx >= 0:
                out.add(ordered_pages[prev_idx])
            if next_idx < len(ordered_pages):
                out.add(ordered_pages[next_idx])
    return [page_no for page_no in ordered_pages if page_no in out]


def _sample_probe_pages(page_numbers: List[int], *, limit: int) -> List[int]:
    ordered = list(dict.fromkeys(page_numbers))
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    if limit == 1:
        return [ordered[0]]
    sample: List[int] = []
    last_idx = len(ordered) - 1
    for pos in range(limit):
        idx = round((last_idx * pos) / (limit - 1))
        page_no = ordered[idx]
        if page_no not in sample:
            sample.append(page_no)
    for page_no in ordered:
        if len(sample) >= limit:
            break
        if page_no not in sample:
            sample.append(page_no)
    return sample


def _preclassify_composition_pages(page_texts: List[str], all_page_numbers: List[int], *, runtime: dict | None = None, config: dict | None = None) -> dict[str, Any]:
    candidate_pages: List[int] = []
    table_candidate_pages: List[int] = []
    text_candidate_pages: List[int] = []
    sicro_candidate_pages: List[int] = []
    scores: dict[int, int] = {}
    strong_pages: List[int] = []
    page_profiles: dict[int, dict[str, Any]] = {}

    for offset, page_no in enumerate(all_page_numbers):
        page_text = page_texts[offset] if offset < len(page_texts) else ""
        signals = _page_composition_signals(page_text, runtime=runtime, config=config)
        scores[page_no] = int(signals.get("score") or 0)
        if signals.get("contains_data"):
            candidate_pages.append(page_no)
        if signals.get("table_candidate"):
            table_candidate_pages.append(page_no)
        if signals.get("text_candidate"):
            text_candidate_pages.append(page_no)
        if signals.get("sicro_candidate"):
            sicro_candidate_pages.append(page_no)
        if signals.get("strong"):
            strong_pages.append(page_no)

        regime = str(signals.get("regime") or "generic")
        pure_sicro = bool(signals.get("pure_sicro"))
        effort = "light"
        if pure_sicro:
            effort = "light"
        elif regime == "misto":
            effort = "standard"
            if bool(signals.get("tipo_candidate")) and int(signals.get("score") or 0) >= 14 and int(signals.get("non_sicro_bank_hits") or 0) >= 2:
                effort = "heavy"
        elif bool(signals.get("tipo_candidate")):
            effort = "standard"
            if int(signals.get("tipo_header_hits") or 0) <= 0 and int(signals.get("tipo_value_hits") or 0) < 3:
                effort = "light"
        elif int(signals.get("header_hits") or 0) + int(signals.get("item_header_hits") or 0) >= 2 and int(signals.get("structural_hits") or 0) >= 1:
            effort = "light"
        elif int(signals.get("score") or 0) >= 14:
            effort = "standard"

        dedicated_sicro = bool(
            pure_sicro
            and signals.get("sicro_candidate")
            and (
                regime == "sicro_like"
                or (
                    int(signals.get("non_sicro_bank_hits") or 0) <= 1
                    and not bool(signals.get("tipo_candidate"))
                    and int(signals.get("header_hits") or 0) <= 1
                    and int(signals.get("structural_hits") or 0) >= 2
                )
            )
        )

        page_profiles[page_no] = {
            "score": int(signals.get("score") or 0),
            "effort": effort,
            "contains_data": bool(signals.get("contains_data")),
            "table_candidate": bool(signals.get("table_candidate")),
            "text_candidate": bool(signals.get("text_candidate")),
            "strong": bool(signals.get("strong")),
            "sicro_candidate": bool(signals.get("sicro_candidate")),
            "tipo_candidate": bool(signals.get("tipo_candidate")),
            "tipo_header_hits": int(signals.get("tipo_header_hits") or 0),
            "tipo_value_hits": int(signals.get("tipo_value_hits") or 0),
            "regime": regime,
            "pure_sicro": pure_sicro,
            "dedicated_sicro": dedicated_sicro,
            "non_sicro_bank_hits": int(signals.get("non_sicro_bank_hits") or 0),
            "sicro_sections": list(signals.get("sicro_sections") or []),
        }

    if not candidate_pages:
        candidate_pages = list(all_page_numbers)
    if not text_candidate_pages:
        text_candidate_pages = list(candidate_pages)
    if not table_candidate_pages:
        table_candidate_pages = list(strong_pages or candidate_pages)

    radius = _resolve_text_candidate_neighbor_buffer(config)
    buffered_text_pages = _buffer_adjacent_pages(text_candidate_pages, all_page_numbers, radius=radius)
    if not buffered_text_pages:
        buffered_text_pages = list(candidate_pages)

    if sicro_candidate_pages:
        sicro_candidate_pages = _buffer_adjacent_pages(sicro_candidate_pages, all_page_numbers, radius=1)

    layout_templates = _build_interval_layout_templates(page_texts, all_page_numbers, page_profiles, config=config)

    metrics = dict(layout_templates.get("metrics") or {})
    metrics.setdefault("candidate_pages", len(candidate_pages))
    metrics.setdefault("table_candidate_pages", len(table_candidate_pages))
    metrics.setdefault("text_candidate_pages", len(buffered_text_pages))
    metrics.setdefault("strong_pages", len(strong_pages))
    metrics.setdefault("sicro_candidate_pages", len(sicro_candidate_pages))
    return {
        "candidate_pages": list(candidate_pages),
        "table_candidate_pages": list(table_candidate_pages),
        "text_candidate_pages": list(buffered_text_pages),
        "sicro_candidate_pages": list(sicro_candidate_pages),
        "scores": scores,
        "strong_pages": strong_pages,
        "page_profiles": page_profiles,
        "layout_templates": layout_templates,
        "blocks": list(layout_templates.get("blocks") or []),
        "blocks_by_id": dict(layout_templates.get("blocks_by_id") or {}),
        "pure_sicro_pages": list(layout_templates.get("pure_sicro_pages") or []),
        "dedicated_sicro_pages": list(layout_templates.get("dedicated_sicro_pages") or []),
        "metrics": metrics,
    }


def _extract_tables(
    page=None,
    *,
    page_no: int | None = None,
    pdf_session: PdfDocumentSession | None = None,
    runtime: dict | None = None,
) -> List[List[List[str]]]:
    """
    O pdfplumber costuma devolver duas leituras concorrentes da mesma página:
    uma baseada em linhas (mais estável) e outra textual (mais fragmentada).

    Para evitar duplicação e vazamento de blocos, priorizamos as tabelas do modo
    com linhas sempre que ele já consegue enxergar tabelas de composição; o modo
    textual vira apenas fallback.
    """
    if pdf_session is not None and page_no is not None:
        perf = ((runtime or {}).get("performance") or {}) if isinstance(runtime, dict) else {}
        table_structure_enabled = bool(perf.get("table_structure_enabled", True))
        fused_comp_tables: List[List[List[str]]] = []
        if table_structure_enabled:
            profile = dict((((runtime or {}).get("context") or {}).get("document_profile") or {})) if isinstance(runtime, dict) else {}
            try:
                candidates = build_table_candidates(pdf_session, page_no, family="composition", profile=profile)
            except Exception:
                candidates = []
            if candidates:
                fused = fuse_table_candidates(candidates)
                best_rows = list(fused.get("best_rows") or [])
                if best_rows and (fused.get("matched") or _looks_like_comp_table(best_rows, runtime=runtime)):
                    fused_comp_tables.append(best_rows)
        pymupdf_tables = pymupdf_tables_as_matrices(pdf_session, page_no, runtime=runtime) if table_structure_enabled else []
        pymupdf_comp_tables = [t for t in pymupdf_tables if _looks_like_comp_table(t, runtime=runtime)]
        line_tables = pdf_session.get_tables(page_no, table_settings=TABLE_SETTINGS_LINES)
        line_comp_tables = [t for t in line_tables if _looks_like_comp_table(t, runtime=runtime)]
        if fused_comp_tables or pymupdf_comp_tables or line_comp_tables:
            merged = []
            seen = set()
            for table in list(fused_comp_tables) + list(pymupdf_comp_tables) + list(line_comp_tables):
                marker = repr(table[:8])
                if marker in seen:
                    continue
                seen.add(marker)
                merged.append(table)
            return sorted(merged, key=_table_quality_score, reverse=True)
        text_tables = pdf_session.get_tables(page_no, table_settings=TABLE_SETTINGS_TEXT)
        text_comp_tables = [t for t in text_tables if _looks_like_comp_table(t, runtime=runtime)]
        if fused_comp_tables or pymupdf_comp_tables or text_comp_tables:
            merged = []
            seen = set()
            for table in list(fused_comp_tables) + list(pymupdf_comp_tables) + list(text_comp_tables):
                marker = repr(table[:8])
                if marker in seen:
                    continue
                seen.add(marker)
                merged.append(table)
            return sorted(merged, key=_table_quality_score, reverse=True)
        return []

    if page is None:
        return []

    line_tables = page.extract_tables(table_settings=TABLE_SETTINGS_LINES) or []
    line_comp_tables = [t for t in line_tables if _looks_like_comp_table(t, runtime=runtime)]
    if line_comp_tables:
        return sorted(line_comp_tables, key=_table_quality_score, reverse=True)

    text_tables = page.extract_tables(table_settings=TABLE_SETTINGS_TEXT) or []
    text_comp_tables = [t for t in text_tables if _looks_like_comp_table(t, runtime=runtime)]
    return sorted(text_comp_tables, key=_table_quality_score, reverse=True)


def _looks_like_header(row: List[str], runtime: dict | None = None) -> bool:
    if runtime and runtime.get("header_cfg"):
        return is_header_row(row, runtime["header_cfg"], min_hits=4)
    up = _norm(" ".join(_clean(c) for c in row if c))
    signals = ["CODIGO", "CÓDIGO", "BANCO", "DESCRICAO", "DESCRIÇÃO", "UND", "QUANT", "VALOR", "TOTAL"]
    return sum(1 for s in signals if s in up) >= 5


def _row_starts_new_comp_table(cells: List[str], runtime: dict | None = None) -> tuple[bool, str]:
    if not cells:
        return False, ""
    first = _clean(cells[0]) if len(cells) > 0 else ""
    if not _is_item_id(first):
        return False, ""
    tail = cells[1:]
    if runtime and is_header_row(tail, runtime["header_cfg"], min_hits=2):
        return True, first
    second = _clean(cells[1]) if len(cells) > 1 else ""
    if _norm(second) in {"CODIGO", "CÓDIGO"}:
        return True, first
    return False, ""


def _looks_like_cost_footer(cells: List[str], runtime: dict | None = None) -> bool:
    full = _norm(" ".join(cells))
    if runtime:
        for marker in runtime.get("footer_markers", []):
            if marker and (norm_text(full).startswith(marker) or marker in norm_text(full)):
                return True
    return bool(full) and ("VALOR COM BDI" in full or full.startswith("MO SEM") or "MO COM LS" in full)


def _looks_like_comp_table(table: List[List[str]], runtime: dict | None = None) -> bool:
    if not table:
        return False
    for r in table[:25]:
        if r and _looks_like_header(r, runtime=runtime):
            return True
    for r in table[:80]:
        if not r:
            continue
        full = _norm(" ".join(_clean(c) for c in r if c))
        if "COMPOS" in full or "INSUMO" in full:
            return True
    return False


def _row_label_text(cells: List[str]) -> str:
    first = _clean(cells[0]) if cells else ""
    second = _clean(cells[1]) if len(cells) > 1 else ""
    label = " ".join(part for part in [first, second] if part).strip()
    return _norm(label)


def _row_kind(cells: List[str], runtime: dict | None = None) -> str:
    label = _row_label_text(cells)
    if not label:
        return ""

    first_label = norm_text(_clean(cells[0]) if cells else "")
    first_compact = first_label.replace(" ", "")
    label_norm = norm_text(label)
    label_compact = label_norm.replace(" ", "")

    # Fast-path robusto para células quebradas como "Composiçã o Auxiliar".
    if first_label.startswith("insumo"):
        return "INSUMO"
    if "auxiliar" in first_label and (
        first_label.startswith("compos")
        or first_compact.startswith("composicaoauxiliar")
        or first_compact.startswith("comp.auxiliar")
        or first_label.startswith("auxiliar")
    ):
        return "AUXILIAR"

    if runtime:
        labels_cfg = ((runtime.get("config") or {}).get("normalization") or {}).get("composition_labels") or {}
        aux_aliases = list((labels_cfg.get("auxiliar") or [])) or ["COMPOSIÇÃO AUXILIAR", "COMPOSICAO AUXILIAR", "AUXILIAR", "COMP. AUXILIAR"]
        ins_aliases = list((labels_cfg.get("insumo") or [])) or ["INSUMO", "INSUMOS"]
        comp_aliases = list((labels_cfg.get("composicao") or [])) or ["COMPOSIÇÃO", "COMPOSICAO", "COMPOS", "COMP."]

        def _matches_any(aliases: List[str]) -> bool:
            for alias in aliases:
                alias_norm = norm_text(alias)
                if not alias_norm:
                    continue
                alias_compact = alias_norm.replace(" ", "")
                if label_norm.startswith(alias_norm) or label_compact.startswith(alias_compact):
                    return True
            return False

        if _matches_any(aux_aliases):
            return "AUXILIAR"
        if _matches_any(ins_aliases):
            return "INSUMO"
        if _matches_any(comp_aliases):
            return "COMPOSICAO"

    if label.startswith("INSUMO"):
        return "INSUMO"
    if label.startswith(("COMPOS", "COMPOSIÇ", "COMPOSICAO")):
        if "AUXILIAR" in label:
            return "AUXILIAR"
        return "COMPOSICAO"
    return ""


def _row_kind_table(cells: List[str], runtime: dict | None = None) -> str:
    """
    Classificação mais rígida para linhas extraídas por tabela.
    Usa a primeira célula como fonte principal de verdade, o que evita que
    quebras como "Composiçã o Auxiliar" virem "COMPOSICAO" comum e contaminem
    blocos irmãos sem item.
    """
    first_label = norm_text(_clean(cells[0]) if cells else "")
    first_compact = first_label.replace(" ", "")
    if not first_label:
        return _row_kind(cells, runtime=runtime)
    if first_label.startswith("insumo"):
        return "INSUMO"
    if "auxiliar" in first_label and (
        first_label.startswith("compos")
        or first_compact.startswith("composicaoauxiliar")
        or first_compact.startswith("comp.auxiliar")
        or first_label.startswith("auxiliar")
    ):
        return "AUXILIAR"
    if first_label.startswith("compos") or first_compact.startswith("composicao") or first_compact.startswith("comp."):
        return "COMPOSICAO"
    return _row_kind(cells, runtime=runtime)


def _join_bank_tokens(tokens: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "SINAP" and i + 1 < len(tokens) and tokens[i + 1] == "I":
            out.append("SINAPI")
            i += 2
            continue
        out.append(t)
        i += 1
    return out


def _canon_bank(bank: str, runtime: dict | None = None) -> str:
    return canonical_bank(bank, config=(runtime or {}).get("config")) if runtime else canonical_bank(bank)


def _is_strong_code_candidate(raw: str) -> bool:
    raw = _clean(raw)
    if not raw:
        return False
    if ("," in raw or "." in raw) and parse_ptbr_number(raw) is not None:
        return False
    cand = _normalize_code_candidate(raw)
    key = _normalize_code_key_part(cand)
    if not key:
        return False
    if any(key.startswith(prefix) for prefix in STRUCTURAL_LABEL_PREFIXES):
        return False
    # Accept PDF-faithful codes with slash/dot/hyphen/spaces, while rejecting descriptions.
    return looks_like_code(cand) or bool(RE_CODE_CAND.fullmatch(key))
def _extract_code_bank(cells: List[str], runtime: dict | None = None) -> Tuple[str, str]:
    # caminho preferencial: colunas explícitas Código/Banco
    if len(cells) >= 3:
        raw_code = _clean(cells[1])
        raw_bank = _clean(cells[2])
        bank_norm = _canon_bank(raw_bank, runtime=runtime)
        known_banks = _known_banks(runtime)
        if bank_norm in known_banks and _is_strong_code_candidate(raw_code):
            code = _normalize_code_candidate(raw_code)
            return code, bank_norm

    tokens: List[str] = []
    early_cells = cells[:4] if cells else []
    for c in early_cells:
        t = _norm(c)
        if t:
            tokens.extend(t.split())
    tokens = _join_bank_tokens(tokens)

    bank = ""
    for t in tokens:
        canon = _canon_bank(t, runtime=runtime)
        if canon in (_known_banks(runtime)):
            bank = canon
            break

    blacklist = {
        "COMPOSIÇÃO",
        "COMPOSICAO",
        "COMPOSIÇÃ",
        "COMPOSIÇ",
        "COMPOSIC",
        "AUXILIAR",
        "INSUMO",
        "CODIGO",
        "CÓDIGO",
        "BANCO",
    }
    code = ""
    if bank:
        try:
            bank_idx = next(i for i, tok in enumerate(tokens) if _canon_bank(tok, runtime=runtime) == bank)
        except StopIteration:
            bank_idx = -1
        if bank_idx > 0:
            code = _extract_joined_code(tokens, bank_idx)

    if not code:
        for cell in early_cells:
            raw = _clean(cell)
            if not raw:
                continue
            for part in raw.split():
                part_up = part.upper()
                if part_up in blacklist or _canon_bank(part_up, runtime=runtime) == bank:
                    continue
                if _is_strong_code_candidate(part):
                    code = _normalize_code_candidate(part)
                    break
            if code:
                break

    return code, bank

def _looks_like_text_section_heading(line: str) -> bool:
    clean_line = _clean(line)
    if not clean_line:
        return False
    if RE_TEXT_SECTION_HEADING.match(clean_line):
        return True
    norm = _norm(clean_line)
    return norm.startswith(("composicoes analiticas", "composicoes principais", "composicoes auxiliares"))


def _looks_like_explicit_comp_header_line(line: str, runtime: dict | None = None) -> bool:
    clean_line = _clean(line)
    if not clean_line:
        return False
    norm = _norm(clean_line)
    if RE_ITEM_HEADER_TEXT.match(norm) or RE_TABLE_HEADER_TEXT.match(norm):
        return True
    has_codigo = "codigo" in norm or "código" in clean_line.lower()
    has_banco = "banco" in norm
    if not (has_codigo and has_banco):
        return False
    extra_hits = sum(1 for token in ("descricao", "descrição", "und", "quant", "valor", "total") if token in norm or token in clean_line.lower())
    return extra_hits >= 2


def _looks_like_unit_token(token: str) -> bool:
    tok = _clean(token).upper().strip(".,:;()[]{}")
    tok = tok.replace("M2", "M²").replace("M3", "M³")
    return tok in {"UN", "UND", "M", "M²", "M³", "KG", "H", "MES", "MÊS", "%", "T", "L", "M3XKM", "KM"}


def _looks_like_tail_unit_token(token: str) -> bool:
    tok = _clean(token).upper().strip(".,:;()[]{}")
    if not tok or tok in _TAIL_UNIT_BLACKLIST:
        return False
    if tok == "M2":
        tok = "M²"
    if tok == "M3":
        tok = "M³"
    return bool(re.fullmatch(r"[A-Z/%²³]{1,10}", tok))


def _scan_tail_candidate_windows(tokens: List[str], *, reverse: bool = False) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    if len(tokens) < 4:
        return candidates
    indexes = range(len(tokens) - 3)
    if reverse:
        indexes = range(len(tokens) - 4, -1, -1)
    for idx in indexes:
        und_raw, q_raw, v_raw, t_raw = tokens[idx: idx + 4]
        if not _looks_like_tail_unit_token(und_raw):
            continue
        if not (RE_NUM.fullmatch(q_raw) and RE_NUM.fullmatch(v_raw) and RE_NUM.fullmatch(t_raw)):
            continue
        quant = parse_ptbr_number(q_raw)
        valor = parse_ptbr_number(v_raw)
        total = parse_ptbr_number(t_raw)
        if quant is None or valor is None or total is None:
            continue
        und = und_raw.replace("M2", "M²").replace("M3", "M³")
        candidates.append({
            "und": und,
            "quant": quant,
            "valor_unit": valor,
            "total": total,
            "raw_tokens": [und_raw, q_raw, v_raw, t_raw],
            "raw_fragment": " ".join([und_raw, q_raw, v_raw, t_raw]),
            "token_index": idx,
        })
    return candidates


def _choose_tail_candidate_from_text(text: str) -> Dict[str, Any]:
    clean_text = _clean(text)
    tokens = _join_bank_tokens([t.upper() for t in clean_text.split()])
    reverse_candidates = _scan_tail_candidate_windows(tokens, reverse=True)
    forward_candidates = _scan_tail_candidate_windows(tokens, reverse=False)
    reverse = reverse_candidates[0] if reverse_candidates else None
    forward = forward_candidates[0] if forward_candidates else None
    selected = None
    status = "missing"
    if reverse and forward:
        same = all(
            reverse.get(k) == forward.get(k)
            for k in ("und", "quant", "valor_unit", "total")
        )
        if same:
            selected = reverse
            status = "consistent"
        else:
            selected = reverse
            status = "ambiguous"
    elif reverse:
        selected = reverse
        status = "reverse_only"
    elif forward:
        selected = forward
        status = "forward_only"
    else:
        selected = None
        status = "missing"
    return {
        "status": status,
        "selected": selected,
        "forward": forward,
        "reverse": reverse,
    }


def _tail_info_payload(tail_info: Dict[str, Any]) -> Dict[str, Any]:
    selected = dict(tail_info.get("selected") or {})
    forward = dict(tail_info.get("forward") or {})
    reverse = dict(tail_info.get("reverse") or {})
    return {
        "status": tail_info.get("status") or "missing",
        "selected": {k: selected.get(k) for k in ("und", "quant", "valor_unit", "total") if selected.get(k) not in (None, "")},
        "forward": {k: forward.get(k) for k in ("und", "quant", "valor_unit", "total") if forward.get(k) not in (None, "")},
        "reverse": {k: reverse.get(k) for k in ("und", "quant", "valor_unit", "total") if reverse.get(k) not in (None, "")},
    }


def _strip_tail_fragment(text: str, raw_fragment: str) -> str:
    assembled = _clean(text)
    fragment = _clean(raw_fragment)
    if not assembled or not fragment:
        return assembled
    if assembled.upper().endswith(fragment.upper()):
        return assembled[: len(assembled) - len(fragment)].rstrip()
    return re.sub(rf"{re.escape(fragment)}\s*$", "", assembled, flags=re.IGNORECASE).strip()


def _extract_tail_values(cells: List[str]) -> Tuple[str, Optional[float], Optional[float], Optional[float]]:
    assembled = _clean(" ".join(_clean(c) for c in cells if _clean(c)))
    tail_info = _choose_tail_candidate_from_text(assembled)
    selected = tail_info.get("selected") or {}
    if selected:
        return (
            str(selected.get("und") or ""),
            selected.get("quant"),
            selected.get("valor_unit"),
            selected.get("total"),
        )

    tokens: List[str] = []
    for c in cells:
        c = _clean(c)
        if c:
            tokens.extend(c.split())
    tokens = _join_bank_tokens([t.upper() for t in tokens])

    nums: List[str] = []
    for t in reversed(tokens):
        if RE_NUM.fullmatch(t):
            nums.append(t)
            if len(nums) >= 3:
                break

    total = parse_ptbr_number(nums[0]) if len(nums) > 0 else None
    valor_unit = parse_ptbr_number(nums[1]) if len(nums) > 1 else None
    quant = parse_ptbr_number(nums[2]) if len(nums) > 2 else None

    und = ""
    if len(nums) > 2:
        try:
            idx_q = tokens.index(nums[2])
            if idx_q - 1 >= 0:
                cand = tokens[idx_q - 1]
                if _looks_like_tail_unit_token(cand):
                    und = cand.replace("M2", "M²").replace("M3", "M³")
        except ValueError:
            pass

    return und, quant, valor_unit, total


def _extract_description(cells: List[str], code: str, bank: str, dynamic_markers: List[str] | None = None, *, finalize: bool = True) -> str:
    preferred = _clean(cells[3]) if len(cells) >= 4 else ""
    if preferred:
        return _sanitize_description(preferred, code=code, bank=bank, dynamic_markers=dynamic_markers) if finalize else _lightweight_clean_description(preferred, code=code, bank=bank)

    full = " ".join(cells)
    full = re.sub(r"(?i)\b(composi[cç][aã]o|auxiliar|insumo)\b", " ", full)
    if code:
        full = full.replace(code, " ")
    if bank:
        full = full.replace(bank, " ")
    full = re.sub(r"\s+", " ", full).strip()
    return _sanitize_description(full, code=code, bank=bank, dynamic_markers=dynamic_markers) if finalize else _lightweight_clean_description(full, code=code, bank=bank)
def _find_table_item_id(table: List[List[str]]) -> str:
    for r in table[:40]:
        if not r:
            continue
        c0 = _clean(r[0]) if len(r) > 0 else ""
        if _is_item_id(c0):
            return c0
    return ""


def _find_table_header_mapping(table: List[List[str]], runtime: dict | None = None) -> tuple[dict[str, int], int | None]:
    cfg = (runtime or {}).get("header_cfg") or {}
    best_mapping: dict[str, int] = {}
    best_idx: int | None = None
    best_score = -1
    for idx, row in enumerate(table[:40]):
        if not row:
            continue
        cells = [_clean(c) for c in row if c is not None]
        if not any(cells):
            continue
        row_variants = [cells]
        if len(cells) > 1:
            row_variants.append(cells[1:])
        for variant in row_variants:
            info = resolve_header_cells(variant, cfg)
            mapping = dict(info.get("mapping") or {})
            score = len(mapping)
            if mapping and score > best_score:
                best_score = score
                best_mapping = mapping
                best_idx = idx
            if mapping and not info.get("missing"):
                return mapping, idx
    return best_mapping, best_idx


def _canonicalize_table_row(cells: List[str], mapping: dict[str, int]) -> List[str]:
    cleaned = [_clean(c) for c in cells if c is not None]
    if not cleaned:
        return []
    if not mapping:
        return cleaned

    offset = 0
    label = ""
    first_idx = min(mapping.values()) if mapping else 1
    leading = cleaned[0] if cleaned else ""
    if mapping.get("codigo") == 0 and _kind_from_structured_label(leading):
        label = leading
        offset = 1
    else:
        label = " ".join(part for part in cleaned[:first_idx] if part).strip()

    def _cell(key: str) -> str:
        idx = mapping.get(key)
        if idx is None:
            return ""
        idx += offset
        return cleaned[idx] if 0 <= idx < len(cleaned) else ""

    return [
        label,
        _cell("codigo"),
        _cell("banco"),
        _cell("descricao"),
        _cell("tipo"),
        _cell("und"),
        _cell("quant"),
        _cell("valor_unit"),
        _cell("total"),
    ]


def _find_start_index(table: List[List[str]], runtime: dict | None = None) -> int:
    first_header_idx: int | None = None
    first_data_idx: int | None = None
    for i, r in enumerate(table[:40]):
        if not r:
            continue
        cells = [_clean(c) for c in r if c is not None]
        if not any(cells):
            continue
        if _looks_like_header(cells, runtime=runtime) and first_header_idx is None:
            first_header_idx = i
        if _row_kind(cells, runtime=runtime) and first_data_idx is None:
            first_data_idx = i
    if first_data_idx is not None and (first_header_idx is None or first_data_idx < first_header_idx):
        return first_data_idx
    if first_header_idx is not None:
        return first_header_idx + 1
    return 0


def _make_line(cells: List[str], dynamic_markers: List[str] | None = None, runtime: dict | None = None, *, finalize_text: bool = True, kind: str = "") -> Tuple[LinhaComposicao, str]:
    code, bank = _extract_code_bank(cells, runtime=runtime)

    tipo = _sanitize_tipo(cells[4]) if len(cells) >= 5 else ""
    if _looks_like_unit_token(tipo):
        tipo = ""
    und_raw = _clean(cells[5]) if len(cells) >= 6 else ""
    quant_raw = _clean(cells[6]) if len(cells) >= 7 else ""
    valor_unit_raw = _clean(cells[7]) if len(cells) >= 8 else ""
    total_raw = _clean(cells[8]) if len(cells) >= 9 else ""
    und = und_raw
    quant = parse_ptbr_number(quant_raw) if quant_raw else None
    valor_unit = parse_ptbr_number(valor_unit_raw) if valor_unit_raw else None
    total = parse_ptbr_number(total_raw) if total_raw else None

    tail_info = _choose_tail_candidate_from_text(" ".join(_clean(c) for c in cells if _clean(c)))
    selected_tail = tail_info.get("selected") or {}
    selected_raw = list(selected_tail.get("raw_tokens") or [])
    if not und or quant is None or valor_unit is None or total is None:
        und = und or str(selected_tail.get("und") or "")
        if quant is None and selected_tail.get("quant") is not None:
            quant = selected_tail.get("quant")
            quant_raw = selected_raw[1] if len(selected_raw) >= 4 else quant_raw
        if valor_unit is None and selected_tail.get("valor_unit") is not None:
            valor_unit = selected_tail.get("valor_unit")
            valor_unit_raw = selected_raw[2] if len(selected_raw) >= 4 else valor_unit_raw
        if total is None and selected_tail.get("total") is not None:
            total = selected_tail.get("total")
            total_raw = selected_raw[3] if len(selected_raw) >= 4 else total_raw
        if not und or quant is None or valor_unit is None or total is None:
            und2, quant2, valor_unit2, total2 = _extract_tail_values(cells)
            und = und or und2
            quant = quant if quant is not None else quant2
            valor_unit = valor_unit if valor_unit is not None else valor_unit2
            total = total if total is not None else total2

    desc = _extract_description(cells, code, bank, dynamic_markers=dynamic_markers, finalize=finalize_text)
    if tipo and desc and desc.upper().endswith(tipo.upper()):
        desc = desc[: -len(tipo)].rstrip(" -,:;")

    line = LinhaComposicao(
        codigo=_normalize_code_candidate(code),
        banco=_canon_bank(bank, runtime=runtime),
        descricao=desc,
        natureza=_structural_nature(kind),
        tipo=tipo,
        und=und,
        quant=quant,
        valor_unit=valor_unit,
        total=total,
        banco_coluna=_canon_bank(bank, runtime=runtime),
    )
    numeric_src = {}
    if quant_raw:
        numeric_src["quant"] = numeric_source(quant_raw)
    if valor_unit_raw:
        numeric_src["valor_unit"] = numeric_source(valor_unit_raw)
    if total_raw:
        numeric_src["total"] = numeric_source(total_raw)
    if numeric_src:
        line.detalhes["numeric_source"] = numeric_src
    if tail_info.get("status") not in {"consistent", "missing"}:
        line.detalhes["tail_parse"] = _tail_info_payload(tail_info)
    return line, _normalize_ref_key(line.codigo, line.banco)
def _make_insumo(cells: List[str], dynamic_markers: List[str] | None = None, *, finalize_text: bool = True, runtime: dict | None = None) -> LinhaInsumo:
    line, _ = _make_line(cells, dynamic_markers=dynamic_markers, runtime=runtime, finalize_text=finalize_text, kind="INSUMO")
    return LinhaInsumo(**line.model_dump())
def _merge_line(base: LinhaComposicao, new: LinhaComposicao) -> LinhaComposicao:
    if not base.descricao and new.descricao:
        base.descricao = new.descricao
    if not base.natureza and new.natureza:
        base.natureza = new.natureza
    if not base.tipo and new.tipo:
        base.tipo = new.tipo
    if not base.und and new.und:
        base.und = new.und
    if base.quant is None and new.quant is not None:
        base.quant = new.quant
    if base.valor_unit is None and new.valor_unit is not None:
        base.valor_unit = new.valor_unit
    if base.total is None and new.total is not None:
        base.total = new.total
    return base


def _dedup_lines(lines: Iterable[LinhaComposicao]) -> List[LinhaComposicao]:
    seen = set()
    out: List[LinhaComposicao] = []
    for line in lines:
        key = (line.codigo, line.banco, line.quant, line.valor_unit, line.total)
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _dedup_auxiliares(lines: Iterable[LinhaComposicao], parent_key: str = "") -> List[LinhaComposicao]:
    # v60: codigo|banco alone is not enough to deduplicate. The same auxiliary
    # reference can legitimately appear with a different coefficient/total.
    seen = set()
    out: List[LinhaComposicao] = []
    for line in lines:
        line.codigo = _normalize_code_candidate(line.codigo)
        line.banco = _canon_bank(line.banco)
        line.banco_coluna = _canon_bank(line.banco_coluna or line.banco)
        ref_key = _normalize_ref_key(line.codigo, line.banco)
        if ref_key and ref_key == parent_key:
            continue
        key = (
            str(getattr(line, 'natureza', '') or ''),
            line.codigo,
            line.banco,
            _clean(getattr(line, 'und', '') or '').upper(),
            getattr(line, 'quant', None),
            getattr(line, 'valor_unit', None),
            getattr(line, 'total', None),
            _norm_desc_sig(getattr(line, 'descricao', '') or '')[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _prune_auxiliares_against_insumos(auxiliares: Iterable[LinhaComposicao], insumos: Iterable[LinhaInsumo], parent_key: str = "") -> List[LinhaComposicao]:
    insumo_refs = {
        _normalize_ref_key(getattr(ins, "codigo", ""), getattr(ins, "banco", ""))
        for ins in insumos or []
        if getattr(ins, "codigo", "") and getattr(ins, "banco", "")
    }
    out: List[LinhaComposicao] = []
    for line in _dedup_auxiliares(auxiliares, parent_key=parent_key):
        ref_key = _normalize_ref_key(line.codigo, line.banco)
        if ref_key and ref_key in insumo_refs:
            continue
        out.append(line)
    return out


def _norm_desc_sig(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", _norm(text)).strip()


def _num_close(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


@dataclass(frozen=True)
class MatchMeta:
    bank: str
    item: str
    code: str
    desc: str
    desc_sig: str
    tokens: frozenset[str]
    semantic_tokens: frozenset[str]
    anchors: frozenset[str]
    chargrams: frozenset[str]
    unit: str
    valor_unit: Optional[float]
    quant: Optional[float]


_MATCH_DESC_STOPWORDS = {
    "DE", "DA", "DO", "DAS", "DOS", "E", "EM", "COM", "SEM", "PARA", "POR", "NA", "NO", "NAS", "NOS",
    "AF", "OU", "A", "O", "AS", "OS", "UM", "UMA", "UN", "UND", "M", "M2", "M3", "M²", "M³", "T", "%",
}


def _ref_desc(ref: dict) -> str:
    return _clean(ref.get("especificacao") or ref.get("descricao") or "")


def _ref_unit(ref: dict) -> str:
    return _clean(ref.get("und") or "").upper()


def _ref_num(ref: dict, field: str) -> Optional[float]:
    raw = ref.get(field)
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return parse_ptbr_number(str(raw))


def _desc_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[A-Z0-9]+", _norm_desc_sig(normalize_service_text(text)))
    return {t for t in tokens if len(t) > 1 and t not in _MATCH_DESC_STOPWORDS}


_SEMANTIC_STEM_SUFFIXES = (
    "COES", "CAO", "ÇÕES", "ÇÃO", "MENTOS", "MENTO", "DADES", "DADE", "TURAS", "TURA", "EIRAS", "EIRA", "EIROS", "EIRO",
    "IDADES", "IDADE", "ADORES", "ADOR", "ADORAS", "ADORA", "IZADAS", "IZADA", "IZADOS", "IZADO", "ADOS", "ADO", "ADAS", "ADA",
    "IDOS", "IDO", "IDAS", "IDA", "ICOS", "ICO", "ICAS", "ICA", "IVOS", "IVO", "IVAS", "IVA", "AIS", "AL", "S",
)

_SEMANTIC_ALIASES = {
    "FABRIC": {"FABRIC", "PREFABRIC"},
    "MONT_INSTAL": {"MONT", "INSTAL", "FORNEC"},
    "TESOURA": {"TESOURA", "MEIATESOURA"},
    "ICAMENTO": {"ICAMENT", "GUINDAST"},
    "ASFALTO": {"ASFALT"},
    "EMULSAO": {"EMULS"},
    "IMPRIMACAO": {"IMPRIM"},
    "ARGILA": {"ARGIL"},
    "MADEIRA": {"MADEIR"},
    "TRANSPORTE": {"TRANSPORT"},
    "CAMINHAO": {"CAMINHA"},
    "BASCULANTE": {"BASCULANT"},
}


def _semantic_stem(token: str) -> str:
    ascii_token = re.sub(r"[^A-Z0-9]", "", _norm(token))
    if not ascii_token or ascii_token in _MATCH_DESC_STOPWORDS:
        return ""
    stem = ascii_token
    for suffix in _SEMANTIC_STEM_SUFFIXES:
        if len(stem) - len(suffix) >= 4 and stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem.startswith("PRE") and len(stem) > 7:
        stem = stem[3:]
    return stem



def _semantic_tokens(text: str) -> frozenset[str]:
    desc = normalize_service_text(text)
    raw_tokens = _desc_tokens(desc)
    semantic: set[str] = set()
    for token in raw_tokens:
        stem = _semantic_stem(token)
        if not stem:
            continue
        semantic.add(stem)
        for alias, variants in _SEMANTIC_ALIASES.items():
            if any(stem.startswith(variant) for variant in variants):
                semantic.add(alias)
    return frozenset(semantic)



def _anchors_from_tokens(tokens: Iterable[str]) -> frozenset[str]:
    return frozenset(t for t in tokens if len(t) >= 5)



def _chargrams(text: str, n: int = 3) -> frozenset[str]:
    sig = _norm_desc_sig(normalize_service_text(text)).replace(" ", "")
    if not sig:
        return frozenset()
    if len(sig) < n:
        return frozenset({sig})
    return frozenset(sig[i:i+n] for i in range(0, len(sig) - n + 1))



def _desc_similarity_sig(sig_a: str, sig_b: str) -> float:
    if not sig_a or not sig_b:
        return 0.0
    return SequenceMatcher(None, sig_a, sig_b).ratio()



def _token_overlap_sets(tokens_a: set[str] | frozenset[str], tokens_b: set[str] | frozenset[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return len(set(tokens_a) & set(tokens_b)) / max(len(tokens_a), len(tokens_b))



def _anchor_overlap_sets(tokens_a: set[str] | frozenset[str], tokens_b: set[str] | frozenset[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return len(set(tokens_a) & set(tokens_b)) / max(1, min(len(tokens_a), len(tokens_b)))



def _jaccard_overlap_sets(tokens_a: set[str] | frozenset[str], tokens_b: set[str] | frozenset[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    a = set(tokens_a)
    b = set(tokens_b)
    return len(a & b) / max(1, len(a | b))



def _bounded_edit_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()



def _code_relation(ref_code: str, block_code: str) -> str:
    if ref_code and block_code and ref_code == block_code:
        return "exact"
    if ref_code and block_code and _is_probable_truncation_variant(ref_code, block_code):
        return "truncation"
    if ref_code and block_code and _bounded_edit_ratio(ref_code, block_code) >= 0.82:
        return "near_typo"
    return "divergent"



@lru_cache(maxsize=8192)
def _cached_match_text_features(text: str, fast_mode: bool = False) -> tuple[str, str, frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    desc = normalize_service_text(text or "")
    desc_sig = _norm_desc_sig(desc)
    tokens = frozenset(_desc_tokens(desc))
    semantic_tokens = _semantic_tokens(desc)
    anchors = _anchors_from_tokens(tokens)
    chargrams = frozenset() if fast_mode else _chargrams(desc)
    return desc, desc_sig, tokens, semantic_tokens, anchors, chargrams


def _build_ref_match_meta(ref: dict, *, fast_mode: bool = False) -> MatchMeta:
    raw_desc = _ref_desc(ref)
    desc, desc_sig, tokens, semantic_tokens, anchors, chargrams = _cached_match_text_features(raw_desc, fast_mode)
    return MatchMeta(
        bank=_canon_bank(str(ref.get("fonte", "") or "")),
        item=_clean(ref.get("item") or ""),
        code=_normalize_code_candidate(str(ref.get("codigo", "") or "")),
        desc=desc,
        desc_sig=desc_sig,
        tokens=tokens,
        semantic_tokens=semantic_tokens,
        anchors=anchors,
        chargrams=chargrams,
        unit=_ref_unit(ref),
        valor_unit=_ref_num(ref, "custo_unitario_sem_bdi"),
        quant=_ref_num(ref, "quant"),
    )



def _build_block_match_meta(block: RawBlock | BlocoComposicao, *, fast_mode: bool = False) -> Optional[MatchMeta]:
    principal = block.principal if hasattr(block, "principal") else None
    if principal is None:
        return None
    desc, desc_sig, tokens, semantic_tokens, anchors, chargrams = _cached_match_text_features(principal.descricao or "", fast_mode)
    return MatchMeta(
        bank=_canon_bank(principal.banco),
        item=_clean(getattr(block, "item", "") or ""),
        code=_normalize_code_candidate(principal.codigo),
        desc=desc,
        desc_sig=desc_sig,
        tokens=tokens,
        semantic_tokens=semantic_tokens,
        anchors=anchors,
        chargrams=chargrams,
        unit=_clean(principal.und).upper(),
        valor_unit=principal.valor_unit,
        quant=principal.quant,
    )



def _value_close(a: Optional[float], b: Optional[float], rel: float = 0.03, abs_tol: float = 0.1) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b), 1.0))



def _likely_direct_item(ref: dict, config: dict | None = None, context: dict | None = None) -> bool:
    bank = _canon_bank(str(ref.get("fonte", "") or ""))
    code = _normalize_code_candidate(str(ref.get("codigo", "") or ""))
    desc = _norm(_ref_desc(ref))
    rules = ((config or {}).get("matching") or {}).get("direct_item_rules") or {}
    direct_codes = set(str(c or "").strip().upper() for c in (rules.get("direct_item_codes") or []) if str(c or "").strip())
    ai_hints = (context or {}).get("ai_hints") or (config or {}).get("ai_hints") or {}
    if isinstance(ai_hints, dict):
        noise = ai_hints.get("noise_profile") or {}
        direct_codes.update(str(c or "").strip().upper() for c in (noise.get("direct_item_codes") or []) if str(c or "").strip())
    if code.upper() in direct_codes:
        return True
    if rules.get("sinapi_zero_prefixed_codes_are_direct_items", True) and bank == "SINAPI" and (code.startswith("0000") or code.startswith("000")):
        return True
    aquisicao_keywords = rules.get("proprio_aquisicao_keywords") or ["AQUISICAO", "AQUISIÇÃO"]
    if bank in {"PRÓPRIO", "PROPRIO"} and any(str(k).upper() in desc for k in aquisicao_keywords):
        return True
    return False


def _candidate_block_map(principais: Dict[str, BlocoComposicao], auxiliares_globais: Dict[str, BlocoComposicao]) -> Dict[str, BlocoComposicao]:
    merged: Dict[str, BlocoComposicao] = {}
    for source in (auxiliares_globais, principais):
        for key, block in (source or {}).items():
            if key not in merged:
                merged[key] = block
    return merged



def _should_accept_flexible_match(ref: dict, best_score: float, second_score: float, evidence: dict, block: BlocoComposicao, *, fast_mode: bool = False) -> bool:
    ref_item = _clean(ref.get("item") or "")
    same_item = bool(ref_item and _clean(getattr(block, "item", "") or "") == ref_item)
    desc_ratio = float(evidence.get("desc_ratio", 0.0) or 0.0)
    token_ratio = float(evidence.get("token_ratio", 0.0) or 0.0)
    anchor_ratio = float(evidence.get("anchor_ratio", 0.0) or 0.0)
    chargram_ratio = float(evidence.get("chargram_ratio", 0.0) or 0.0)
    semantic_ratio = float(evidence.get("semantic_ratio", 0.0) or 0.0)
    valor_ok = bool(evidence.get("valor_unit_close"))
    unit_ok = bool(evidence.get("unit_equal"))
    code_relation = str(evidence.get("code_relation", "divergent") or "divergent")
    code_divergent = code_relation == "divergent"
    trunc_variant = code_relation == "truncation"
    bank = _canon_bank(str(getattr(getattr(block, "principal", None), "banco", "") or ""))
    non_proprio_strict = fast_mode and bank not in {"PRÓPRIO", "PROPRIO"}
    semantic_peak = max(desc_ratio, chargram_ratio, semantic_ratio)

    if not code_divergent and best_score >= max(18.0, second_score + 2.0):
        return True
    if same_item and valor_ok and desc_ratio >= 0.34 and (unit_ok or not code_divergent):
        return True
    if same_item and valor_ok and unit_ok and (not code_divergent or semantic_peak >= 0.46):
        return True
    if same_item and valor_ok and semantic_ratio >= 0.34 and best_score >= max(14.5, second_score + 1.5):
        return True
    if (not code_divergent or same_item or not non_proprio_strict) and valor_ok and semantic_peak >= 0.44 and anchor_ratio >= 0.18 and best_score >= max(14.0, second_score + 1.0):
        return True
    if trunc_variant and valor_ok and desc_ratio >= 0.30:
        return True
    if code_relation == "near_typo" and valor_ok and unit_ok and semantic_peak >= 0.48:
        return True
    if (not code_divergent or same_item or not non_proprio_strict) and valor_ok and unit_ok and semantic_peak >= 0.55 and token_ratio >= 0.20:
        return True

    if code_divergent:
        if same_item and valor_ok and unit_ok and semantic_peak >= 0.60 and token_ratio >= 0.22 and best_score >= max(16.0, second_score + 2.5):
            return True
        if same_item and valor_ok and semantic_ratio >= 0.34 and best_score >= max(15.0, second_score + 1.5):
            return True
        if non_proprio_strict:
            if valor_ok and unit_ok and semantic_peak >= 0.74 and anchor_ratio >= 0.32 and token_ratio >= 0.22 and best_score >= max(18.5, second_score + 3.0):
                return True
            return False
        if valor_ok and unit_ok and semantic_peak >= 0.64 and anchor_ratio >= 0.24 and best_score >= max(17.0, second_score + 2.5):
            return True
        if valor_ok and desc_ratio >= 0.45 and anchor_ratio >= 0.25 and token_ratio >= 0.10 and best_score >= max(15.0, second_score + 1.0):
            return True
        return False

    if valor_ok and semantic_peak >= 0.45 and anchor_ratio >= 0.25 and best_score >= max(13.0, second_score + 1.0):
        return True
    if valor_ok and semantic_peak >= 0.42 and token_ratio >= 0.22 and anchor_ratio >= 0.30 and best_score >= max(12.0, second_score + 1.0):
        return True
    return False



def _block_match_score_from_meta(ref_meta: MatchMeta, block: RawBlock | BlocoComposicao, block_meta: MatchMeta) -> tuple[float, dict]:
    if block_meta.bank != ref_meta.bank:
        return -1.0, {}

    desc_ratio = _desc_similarity_sig(ref_meta.desc_sig, block_meta.desc_sig)
    token_ratio = _token_overlap_sets(ref_meta.tokens, block_meta.tokens)
    anchor_ratio = _anchor_overlap_sets(ref_meta.anchors, block_meta.anchors)
    chargram_ratio = _jaccard_overlap_sets(ref_meta.chargrams, block_meta.chargrams)
    semantic_ratio = _jaccard_overlap_sets(ref_meta.semantic_tokens, block_meta.semantic_tokens)
    code_relation = _code_relation(ref_meta.code, block_meta.code)

    score = 0.0
    if ref_meta.item and block_meta.item == ref_meta.item:
        score += 8.0
    if code_relation == "exact":
        score += 16.0
    elif code_relation == "truncation":
        score += 8.0
    elif code_relation == "near_typo":
        score += 4.0

    score += desc_ratio * 10.0
    score += token_ratio * 8.0
    score += anchor_ratio * 4.0
    score += chargram_ratio * 6.0
    score += semantic_ratio * 7.0

    if ref_meta.unit and block_meta.unit and ref_meta.unit == block_meta.unit:
        score += 3.0
    if _value_close(ref_meta.valor_unit, block_meta.valor_unit, rel=0.05, abs_tol=0.15):
        score += 6.0
    if _value_close(ref_meta.quant, block_meta.quant, rel=0.05, abs_tol=0.05):
        score += 2.0

    if ref_meta.bank == "PRÓPRIO" and max(desc_ratio, chargram_ratio, semantic_ratio) >= 0.5:
        score += 2.0
    if ref_meta.item and block_meta.item == ref_meta.item and semantic_ratio >= 0.34 and _value_close(ref_meta.valor_unit, block_meta.valor_unit, rel=0.05, abs_tol=0.15):
        score += 2.5

    evidence = {
        "desc_ratio": round(desc_ratio, 4),
        "token_ratio": round(token_ratio, 4),
        "anchor_ratio": round(anchor_ratio, 4),
        "chargram_ratio": round(chargram_ratio, 4),
        "semantic_ratio": round(semantic_ratio, 4),
        "unit_equal": bool(ref_meta.unit and block_meta.unit and ref_meta.unit == block_meta.unit),
        "valor_unit_close": _value_close(ref_meta.valor_unit, block_meta.valor_unit, rel=0.05, abs_tol=0.15),
        "quant_close": _value_close(ref_meta.quant, block_meta.quant, rel=0.05, abs_tol=0.05),
        "codigo_orcamento": ref_meta.code,
        "codigo_composicao": block_meta.code,
        "code_relation": code_relation,
    }
    return score, evidence



def _block_match_score(ref: dict, block: RawBlock | BlocoComposicao) -> tuple[float, dict]:
    block_meta = _build_block_match_meta(block)
    if block_meta is None:
        return -1.0, {}
    return _block_match_score_from_meta(_build_ref_match_meta(ref), block, block_meta)


def _clone_bloco(block: BlocoComposicao) -> BlocoComposicao:
    return BlocoComposicao(**block.model_dump())


def _clone_line(line: LinhaComposicao | LinhaInsumo) -> LinhaComposicao:
    if isinstance(line, LinhaInsumo):
        return LinhaInsumo(**line.model_dump())
    return LinhaComposicao(**line.model_dump())


_ASSOCIATED_RELATION_STATUSES = {"associada_diretamente", "associada_por_indicio"}


def _relation_suspeitas(status: str, codigo_orcamento: str, codigo_composicao: str, evidence: dict | None = None) -> list[str]:
    suspeitas: list[str] = []
    evidence = dict(evidence or {})
    if status == "nao_associada_diretamente_no_orcamento":
        suspeitas.append("sem_item_correspondente_no_sintetico")
    if codigo_orcamento and codigo_composicao and codigo_orcamento != codigo_composicao:
        suspeitas.append("codigo_divergente")
    if status == "associada_por_indicio":
        desc_ratio = float(evidence.get("desc_ratio", 0.0) or 0.0)
        semantic_ratio = float(evidence.get("semantic_ratio", 0.0) or 0.0)
        chargram_ratio = float(evidence.get("chargram_ratio", 0.0) or 0.0)
        anchor_ratio = float(evidence.get("anchor_ratio", 0.0) or 0.0)
        if max(desc_ratio, semantic_ratio, chargram_ratio) < 0.60:
            suspeitas.append("descricao_semantica_parcial")
        if anchor_ratio < 0.28:
            suspeitas.append("ancoras_textuais_limitadas")
    return suspeitas


def _append_orcamento_relation(block: BlocoComposicao, relation: dict) -> None:
    detalhes = dict(block.detalhes or {})
    rels = [dict(r) for r in (detalhes.get("relacoes_orcamento") or []) if isinstance(r, dict)]
    status = str(relation.get("status") or "").strip()
    if status in _ASSOCIATED_RELATION_STATUSES:
        rels = [r for r in rels if str(r.get("status") or "").strip() != "nao_associada_diretamente_no_orcamento"]
    fingerprint = (
        status,
        str(relation.get("item_orcamento") or "").strip(),
        str(relation.get("ref_id_orcamento") or "").strip(),
        str(relation.get("chave_bloco") or "").strip(),
        str(relation.get("codigo_composicao_encontrado") or "").strip(),
    )
    existing = {
        (
            str(r.get("status") or "").strip(),
            str(r.get("item_orcamento") or "").strip(),
            str(r.get("ref_id_orcamento") or "").strip(),
            str(r.get("chave_bloco") or "").strip(),
            str(r.get("codigo_composicao_encontrado") or "").strip(),
        )
        for r in rels
    }
    if fingerprint not in existing:
        rels.append(relation)
    detalhes["relacoes_orcamento"] = rels
    if status in _ASSOCIATED_RELATION_STATUSES or "relacao_orcamento" not in detalhes:
        detalhes["relacao_orcamento"] = relation
    if status == "associada_por_indicio":
        detalhes["vinculo_flexivel"] = {
            "ref_id_orcamento": relation.get("ref_id_orcamento"),
            "item_orcamento": relation.get("item_orcamento"),
            "codigo_orcamento": relation.get("codigo_orcamento"),
            "codigo_composicao_encontrado": relation.get("codigo_composicao_encontrado"),
            "origem_bloco": relation.get("chave_bloco"),
            "score": relation.get("score"),
            "evidencia": relation.get("evidencia"),
            "divergencia_codigo": bool(relation.get("divergencia_codigo")),
        }
    block.detalhes = detalhes


def _iter_orcamento_relations(block: BlocoComposicao) -> list[dict]:
    detalhes = dict(getattr(block, "detalhes", {}) or {})
    rels = [dict(r) for r in (detalhes.get("relacoes_orcamento") or []) if isinstance(r, dict)]
    if not rels and isinstance(detalhes.get("relacao_orcamento"), dict):
        rels = [dict(detalhes.get("relacao_orcamento") or {})]
    return rels


def _prune_relation_debug_fields(clean: Dict[str, Any]) -> Dict[str, Any]:
    clean.pop("relacao_orcamento", None)
    clean.pop("relacoes_orcamento", None)
    clean.pop("vinculo_flexivel", None)
    return clean


def _sanitize_sicro_output_payload(sicro: Dict[str, Any]) -> Dict[str, Any]:
    """Return a clean non-redundant SICRO payload.

    v61.0.20 public contract:
    - one official section tree: ``sicro.secoes.A-F``;
    - no duplicated public aliases (``equipamentos``, ``materiais`` etc.);
    - no evidence/debug-only fields;
    - section C/D/E/F use ``custo`` rather than ``custo_horario``.
    """
    if not isinstance(sicro, dict):
        return {}

    aliases = {
        "A": "equipamentos",
        "B": "mao_obra",
        "C": "materiais",
        "D": "atividades_auxiliares",
        "E": "tempos_fixos",
        "F": "momentos_transporte",
    }
    drop_keys = {"_evidence", "_field_evidence", "_confidence", "raw_trace", "numeric_source", "detalhes"}

    def _prune(obj: Any, *, section: str = "") -> Any:
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in drop_keys:
                    continue
                # Avoid legacy/duplicate result field names in the clean SICRO contract.
                if section in {"C", "D", "E", "F"} and k == "custo_horario":
                    if "custo" not in obj:
                        out["custo"] = _prune(v, section=section)
                    continue
                pv = _prune(v, section=section)
                if pv not in (None, "", [], {}):
                    out[k] = pv
            return out
        if isinstance(obj, list):
            return [x for x in (_prune(v, section=section) for v in obj) if x not in (None, "", [], {})]
        return obj

    def _rows_from_section(value: Any) -> tuple[list[dict], dict]:
        meta: dict[str, Any] = {}
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)], meta
        if isinstance(value, dict):
            rows = value.get("linhas") if isinstance(value.get("linhas"), list) else []
            meta = {k: v for k, v in value.items() if k != "linhas"}
            return [r for r in rows if isinstance(r, dict)], meta
        return [], meta

    secoes_in = sicro.get("secoes") if isinstance(sicro.get("secoes"), dict) else {}
    canonical_sections: Dict[str, Any] = {}
    for sec, public_key in aliases.items():
        rows, meta = _rows_from_section((secoes_in or {}).get(sec))
        if not rows and isinstance(sicro.get(public_key), list):
            rows = [r for r in sicro.get(public_key) if isinstance(r, dict)]
        rows_clean = [_prune(r, section=sec) for r in rows]
        rows_clean = [r for r in rows_clean if isinstance(r, dict) and r]
        if not rows_clean:
            continue
        sec_meta = _prune(meta, section=sec) if isinstance(meta, dict) else {}
        section_out = {
            "nome": sec_meta.get("nome") or public_key,
            "public_key": public_key,
            "linhas": rows_clean,
        }
        for mk in ("total_reportado", "validacao_total"):
            if mk in sec_meta and sec_meta[mk] not in (None, "", [], {}):
                section_out[mk] = sec_meta[mk]
        canonical_sections[sec] = section_out

    result: Dict[str, Any] = {}
    if canonical_sections:
        result["secoes"] = canonical_sections

    for optional in ("resumos", "validacao", "text_integrity", "document_consistency", "document_consistency_warnings", "text_audit_summary"):
        if isinstance(sicro.get(optional), (dict, list)) and sicro.get(optional):
            result[optional] = _prune(sicro.get(optional))

    return {k: v for k, v in result.items() if v not in (None, "", [], {})}

def _clean_output_details(detalhes: Dict[str, Any] | None) -> Dict[str, Any]:
    clean = _prune_relation_debug_fields(dict(detalhes or {}))
    sicro = clean.get("sicro")
    if isinstance(sicro, dict):
        clean["sicro"] = _sanitize_sicro_output_payload(sicro)
    return clean


def _output_block_parts(block: RawBlock) -> tuple[list[LinhaComposicao], list[LinhaInsumo], Dict[str, Any]]:
    detalhes = _clean_output_details(block.detalhes)
    principal = getattr(block, "principal", None)
    banco = _canon_bank(getattr(principal, "banco", "") or "") if principal is not None else ""
    auxiliares = list(block.auxiliares or [])
    if banco == "SICRO":
        return [], [], detalhes
    return auxiliares, list(block.insumos or []), detalhes


def _associated_items_from_blocks(principais: Dict[str, BlocoComposicao]) -> set[str]:
    items: set[str] = set()
    for key, block in (principais or {}).items():
        for rel in _iter_orcamento_relations(block):
            if str(rel.get("status") or "").strip() in _ASSOCIATED_RELATION_STATUSES:
                item = _clean(rel.get("item_orcamento") or "")
                if item:
                    items.add(item)
        if key and key == _normalize_ref_key(getattr(block.principal, "codigo", ""), getattr(block.principal, "banco", "")) and block.item and not _iter_orcamento_relations(block):
            items.add(_clean(block.item))
    return items


def _dispensa_ref_key(ref: dict) -> str:
    item = _clean(ref.get("item") or "")
    key = _clean(ref.get("ref_id") or "")
    return f"{item}|{key}" if item and key else key or item


def _is_probable_truncation_variant(code_a: str, code_b: str) -> bool:
    a = re.sub(r"[^0-9A-Z_]", "", _normalize_code_candidate(code_a))
    b = re.sub(r"[^0-9A-Z_]", "", _normalize_code_candidate(code_b))
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(longer) - len(shorter) > 2:
        return False
    return longer.startswith(shorter)


def _same_line_semantics(base: LinhaComposicao, other: LinhaComposicao) -> bool:
    if _canon_bank(base.banco) != _canon_bank(other.banco):
        return False
    if _norm_desc_sig(base.descricao) != _norm_desc_sig(other.descricao):
        return False
    if _clean(base.und).upper() != _clean(other.und).upper():
        return False
    if not _num_close(base.valor_unit, other.valor_unit):
        return False
    return True


def _merge_raw_blocks(base: RawBlock, other: RawBlock) -> RawBlock:
    if not base.item and other.item:
        base.item = other.item
    if base.principal is None and other.principal is not None:
        base.principal = other.principal
    elif base.principal is not None and other.principal is not None:
        base.principal = _merge_line(base.principal, other.principal)
    if other.page and (not base.page or other.page < base.page):
        base.page = other.page
    if other.page_start and (not base.page_start or other.page_start < base.page_start):
        base.page_start = other.page_start
    if other.page_end and (not base.page_end or other.page_end > base.page_end):
        base.page_end = other.page_end
    for pno in list(other.pages_seen or []):
        _touch_block_page(base, int(pno))
    if other.detalhes:
        merged = dict(base.detalhes or {})
        merged.update(other.detalhes or {})
        base.detalhes = merged
    if not base.closure_reason and other.closure_reason:
        base.closure_reason = other.closure_reason
    parent_key = _normalize_ref_key(base.principal.codigo, base.principal.banco) if base.principal else base.key
    base.auxiliares = _prune_auxiliares_against_insumos(
        list(base.auxiliares) + list(other.auxiliares),
        list(base.insumos) + list(other.insumos),
        parent_key=parent_key,
    )
    base.insumos = [LinhaInsumo(**x.model_dump()) for x in _dedup_lines(list(base.insumos) + list(other.insumos))]
    return base


def _clone_raw_block(block: RawBlock) -> RawBlock:
    return RawBlock(
        item=str(block.item or ""),
        key=str(block.key or ""),
        principal=LinhaComposicao(**block.principal.model_dump()) if block.principal is not None else None,
        auxiliares=[LinhaComposicao(**line.model_dump()) for line in list(block.auxiliares or [])],
        insumos=[LinhaInsumo(**line.model_dump()) for line in list(block.insumos or [])],
        page=int(block.page or 0),
        page_start=int(block.page_start or 0),
        page_end=int(block.page_end or 0),
        pages_seen=list(block.pages_seen or []),
        closure_reason=str(block.closure_reason or ""),
        detalhes=dict(block.detalhes or {}),
    )


def _block_line_total(line: LinhaComposicao | LinhaInsumo | None) -> float | None:
    if line is None:
        return None
    if line.total is not None:
        return float(line.total)
    if line.quant is not None and line.valor_unit is not None:
        return round(float(line.quant) * float(line.valor_unit), 6)
    return None


def _block_missing_field_score(block: RawBlock) -> int:
    score = 0
    rows: List[LinhaComposicao] = []
    if block.principal is not None:
        rows.append(block.principal)
    rows.extend(list(block.auxiliares or []))
    rows.extend(list(block.insumos or []))
    for idx, row in enumerate(rows):
        required = ["codigo", "banco", "descricao"] + (["und", "quant", "valor_unit", "total"] if idx == 0 else ["und", "quant"])
        for field in required:
            value = getattr(row, field, None)
            if value in (None, ""):
                score += 1
    return score


def _block_math_distance(block: RawBlock) -> float:
    principal_total = _block_line_total(block.principal)
    if principal_total is None:
        return float("inf")
    component_total = 0.0
    row_count = 0
    for row in list(block.auxiliares or []) + list(block.insumos or []):
        value = _block_line_total(row)
        if value is None:
            continue
        row_count += 1
        component_total += float(value)
    if row_count <= 0:
        return float("inf")
    return round(abs(float(principal_total) - round(component_total, 6)), 6)


def _block_quality_score(block: RawBlock) -> tuple:
    row_count = len(list(block.auxiliares or [])) + len(list(block.insumos or []))
    pages = len(list(block.pages_seen or []))
    return (
        0 if row_count > 0 else 1,
        _block_math_distance(block),
        _block_missing_field_score(block),
        -row_count,
        -pages,
    )


def _choose_best_block_variant(base: RawBlock, other: RawBlock) -> RawBlock:
    candidates = [
        _clone_raw_block(base),
        _clone_raw_block(other),
        _merge_raw_blocks(_clone_raw_block(base), _clone_raw_block(other)),
    ]
    scored = [(cand, _block_quality_score(cand)) for cand in candidates]
    scored.sort(key=lambda item: item[1])
    return scored[0][0]


def _union_candidate_sets(*groups: Iterable[tuple[str, BlocoComposicao, MatchMeta]]) -> List[tuple[str, BlocoComposicao, MatchMeta]]:
    ordered: List[tuple[str, BlocoComposicao, MatchMeta]] = []
    seen: set[str] = set()
    for group in groups:
        for cand_key, block, block_meta in group or []:
            if cand_key in seen:
                continue
            seen.add(cand_key)
            ordered.append((cand_key, block, block_meta))
    return ordered


def _code_family_candidates(ref_meta: MatchMeta, blocks_by_bank_code: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]]) -> List[tuple[str, BlocoComposicao, MatchMeta]]:
    if not ref_meta.bank or not ref_meta.code:
        return []
    pools: List[Iterable[tuple[str, BlocoComposicao, MatchMeta]]] = []
    exact = blocks_by_bank_code.get((ref_meta.bank, ref_meta.code), [])
    if exact:
        pools.append(exact)
    digits = re.sub(r"[^0-9A-Z_]", "", ref_meta.code)
    if len(digits) >= 6:
        for size in range(len(digits) - 1, max(4, len(digits) - 2), -1):
            prefix = digits[:size]
            prefix_group = blocks_by_bank_code.get((ref_meta.bank, prefix), [])
            if prefix_group:
                pools.append(prefix_group)
    return _union_candidate_sets(*pools)


def _early_match_candidates(
    ref_meta: MatchMeta,
    candidate_pool: List[tuple[str, BlocoComposicao, MatchMeta]],
    *,
    blocks_by_bank_item: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]],
    blocks_by_bank_code: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]],
    blocks_by_bank_unit: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]],
    fast_mode: bool,
) -> List[tuple[str, BlocoComposicao, MatchMeta]]:
    same_item_group = blocks_by_bank_item.get((ref_meta.bank, ref_meta.item), []) if ref_meta.item else []
    code_group = _code_family_candidates(ref_meta, blocks_by_bank_code)
    same_unit_group = blocks_by_bank_unit.get((ref_meta.bank, ref_meta.unit), []) if ref_meta.unit else []

    if same_item_group or code_group:
        narrowed = _union_candidate_sets(same_item_group, code_group)
        if same_unit_group and len(narrowed) < 12:
            narrowed = _union_candidate_sets(narrowed, same_unit_group)
        return narrowed or candidate_pool

    if fast_mode and same_unit_group and 0 < len(same_unit_group) <= max(12, len(candidate_pool) // 3):
        return list(same_unit_group)
    return candidate_pool


def _merge_sicro_blocks(raw_blocks: Dict[str, RawBlock], sicro_blocks: Dict[str, Any]) -> Dict[str, RawBlock]:
    for key, sblock in (sicro_blocks or {}).items():
        principal = getattr(sblock, "principal", None)
        if principal is None:
            continue

        # SICRO has its own domain structure. Convert the dedicated parser output
        # to the public SICRO shape immediately, before the generic SINAPI-like
        # composition pipeline has a chance to reintroduce fields such as
        # descricao/valor_unit/row_uid into section rows.
        materialized = materialize_sicro_block(sblock)
        converted = RawBlock(
            item=getattr(materialized, "item", "") or "",
            key=key,
            principal=getattr(materialized, "principal", None) or principal,
            auxiliares=[],
            insumos=[],
            page_start=int(getattr(materialized, "pagina_inicio", 0) or 0),
            page_end=int(getattr(materialized, "pagina_fim", 0) or 0),
            pages_seen=list(getattr(materialized, "paginas", []) or []),
            detalhes=dict(getattr(materialized, "detalhes", {}) or {}),
        )
        existing = raw_blocks.get(key)
        if existing is None:
            raw_blocks[key] = converted
            continue

        existing_is_sicro = bool(existing.principal and _canon_bank(existing.principal.banco) == "SICRO")
        converted_is_sicro = bool(converted.principal and _canon_bank(converted.principal.banco) == "SICRO")
        if converted_is_sicro:
            # Para blocos SICRO preferimos o parser dedicado, preservando apenas o item já associado.
            if not converted.item and existing.item:
                converted.item = existing.item
            raw_blocks[key] = converted
            continue

        if existing_is_sicro:
            if not existing.item and converted.item:
                existing.item = converted.item
            continue

        raw_blocks[key] = _merge_raw_blocks(existing, converted)
        if converted.detalhes:
            raw_blocks[key].detalhes = {**(existing.detalhes or {}), **converted.detalhes}
    return raw_blocks


def _apply_flexible_ref_resolution(
    orc_refs_all: List[dict],
    principais: Dict[str, BlocoComposicao],
    auxiliares_globais: Dict[str, BlocoComposicao],
    avisos: List[str],
    config: dict | None = None,
) -> tuple[Dict[str, BlocoComposicao], set[str], set[str]]:
    performance_cfg = (config or {}).get("performance") or {}
    profile = str(performance_cfg.get("profile") or "").strip().lower()
    fast_mode = profile in {"browser_fast", "fast"}
    base_shortlist_cap = int(performance_cfg.get("matching_shortlist_cap") or 48 or 0)

    matched_items = _associated_items_from_blocks(principais)
    dispensados: set[str] = set()
    vinculados_flex: set[str] = set()
    candidate_blocks = _candidate_block_map(principais, auxiliares_globais)

    block_meta_by_key: Dict[str, MatchMeta] = {}
    blocks_by_bank: Dict[str, List[tuple[str, BlocoComposicao, MatchMeta]]] = {}
    blocks_by_bank_item: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]] = {}
    blocks_by_bank_code: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]] = {}
    blocks_by_bank_unit: Dict[tuple[str, str], List[tuple[str, BlocoComposicao, MatchMeta]]] = {}
    for cand_key, block in candidate_blocks.items():
        meta = _build_block_match_meta(block, fast_mode=fast_mode)
        if meta is None or not meta.bank:
            continue
        triple = (cand_key, block, meta)
        block_meta_by_key[cand_key] = meta
        blocks_by_bank.setdefault(meta.bank, []).append(triple)
        if meta.item:
            blocks_by_bank_item.setdefault((meta.bank, meta.item), []).append(triple)
        if meta.code:
            blocks_by_bank_code.setdefault((meta.bank, meta.code), []).append(triple)
        if meta.unit:
            blocks_by_bank_unit.setdefault((meta.bank, meta.unit), []).append(triple)

    for ref in orc_refs_all:
        ref_item = _clean(ref.get("item") or "")
        ref_key = _clean(ref.get("ref_id") or "")
        if not ref_item or not ref_key:
            continue
        if ref_key in principais:
            matched_items.add(ref_item)
            direct_block = principais[ref_key]
            principal = getattr(direct_block, "principal", None)
            codigo_comp = _normalize_code_candidate(str(getattr(principal, "codigo", "") or "")) if principal else ""
            codigo_orc = _normalize_code_candidate(str(ref.get("codigo", "") or ""))
            relation = {
                "status": "associada_diretamente",
                "criterio": "codigo_banco",
                "item_orcamento": ref_item,
                "ref_id_orcamento": ref_key,
                "codigo_orcamento": codigo_orc,
                "codigo_composicao_encontrado": codigo_comp,
                "chave_bloco": ref_key,
                "divergencia_codigo": bool(codigo_orc and codigo_comp and codigo_orc != codigo_comp),
                "suspeitas": _relation_suspeitas("associada_diretamente", codigo_orc, codigo_comp),
            }
            _append_orcamento_relation(direct_block, relation)
            continue
        if ref_item in matched_items:
            continue

        ref_meta = _build_ref_match_meta(ref, fast_mode=fast_mode)
        candidate_pool = list(blocks_by_bank.get(ref_meta.bank, []))
        if not candidate_pool:
            if _likely_direct_item(ref, config=config):
                dispensados.add(_dispensa_ref_key(ref))
                avisos.append(
                    f"[composicoes] dispensa de composição analítica para o item {ref_item} ({ref_key}): item direto/material detectado no orçamento."
                )
            continue

        candidate_pool = _early_match_candidates(
            ref_meta,
            candidate_pool,
            blocks_by_bank_item=blocks_by_bank_item,
            blocks_by_bank_code=blocks_by_bank_code,
            blocks_by_bank_unit=blocks_by_bank_unit,
            fast_mode=fast_mode,
        )

        filtered_pool: List[tuple[str, BlocoComposicao, MatchMeta]] = []
        for cand_key, block, block_meta in candidate_pool:
            if cand_key == ref_key:
                continue

            same_item = bool(ref_meta.item and block_meta.item == ref_meta.item)
            code_relation = _code_relation(ref_meta.code, block_meta.code)
            code_match = code_relation in {"exact", "truncation", "near_typo"}
            unit_match = bool(ref_meta.unit and block_meta.unit and ref_meta.unit == block_meta.unit)
            value_close_loose = _value_close(ref_meta.valor_unit, block_meta.valor_unit, rel=0.25, abs_tol=1.0)
            quant_close_loose = _value_close(ref_meta.quant, block_meta.quant, rel=0.20, abs_tol=0.20)
            token_hits = len(ref_meta.tokens & block_meta.tokens) if ref_meta.tokens and block_meta.tokens else 0
            semantic_hits = len(ref_meta.semantic_tokens & block_meta.semantic_tokens) if ref_meta.semantic_tokens and block_meta.semantic_tokens else 0
            anchor_hits = len(ref_meta.anchors & block_meta.anchors) if ref_meta.anchors and block_meta.anchors else 0
            chargram_overlap = _jaccard_overlap_sets(ref_meta.chargrams, block_meta.chargrams)

            if same_item or code_match:
                filtered_pool.append((cand_key, block, block_meta))
                continue
            if unit_match and (value_close_loose or token_hits >= 1 or semantic_hits >= 1 or chargram_overlap >= 0.24):
                filtered_pool.append((cand_key, block, block_meta))
                continue
            if value_close_loose and (token_hits >= 2 or semantic_hits >= 2 or anchor_hits >= 1 or quant_close_loose or chargram_overlap >= 0.28):
                filtered_pool.append((cand_key, block, block_meta))
                continue
            if token_hits >= 3 or semantic_hits >= 2 or anchor_hits >= 2 or chargram_overlap >= 0.34:
                filtered_pool.append((cand_key, block, block_meta))

        if not filtered_pool:
            if fast_mode:
                ranked_pool = []
                for cand_key, block, block_meta in candidate_pool:
                    same_item = bool(ref_meta.item and block_meta.item == ref_meta.item)
                    code_relation = _code_relation(ref_meta.code, block_meta.code)
                    unit_match = bool(ref_meta.unit and block_meta.unit and ref_meta.unit == block_meta.unit)
                    value_close_loose = _value_close(ref_meta.valor_unit, block_meta.valor_unit, rel=0.18, abs_tol=0.75)
                    quant_close_loose = _value_close(ref_meta.quant, block_meta.quant, rel=0.15, abs_tol=0.15)
                    token_hits = len(ref_meta.tokens & block_meta.tokens) if ref_meta.tokens and block_meta.tokens else 0
                    semantic_hits = len(ref_meta.semantic_tokens & block_meta.semantic_tokens) if ref_meta.semantic_tokens and block_meta.semantic_tokens else 0
                    anchor_hits = len(ref_meta.anchors & block_meta.anchors) if ref_meta.anchors and block_meta.anchors else 0
                    cheap_score = 0.0
                    if same_item:
                        cheap_score += 10.0
                    if code_relation == "exact":
                        cheap_score += 16.0
                    elif code_relation in {"truncation", "near_typo"}:
                        cheap_score += 8.0
                    if unit_match:
                        cheap_score += 4.0
                    if value_close_loose:
                        cheap_score += 6.0
                    if quant_close_loose:
                        cheap_score += 1.0
                    cheap_score += min(token_hits, 4) * 1.4
                    cheap_score += min(semantic_hits, 4) * 1.3
                    cheap_score += min(anchor_hits, 3) * 0.9
                    if cheap_score > 0:
                        ranked_pool.append((cheap_score, cand_key, block, block_meta))
                ranked_pool.sort(key=lambda x: x[0], reverse=True)
                shortlist_cap = _effective_matching_shortlist_cap(base_shortlist_cap, fast_mode=fast_mode, total_refs=len(orc_refs_all), candidate_count=len(candidate_pool))
                filtered_pool = [(cand_key, block, block_meta) for _, cand_key, block, block_meta in ranked_pool[:max(6, shortlist_cap or 6)]]
            else:
                filtered_pool = candidate_pool

        shortlist_cap = _effective_matching_shortlist_cap(base_shortlist_cap, fast_mode=fast_mode, total_refs=len(orc_refs_all), candidate_count=len(filtered_pool))
        if shortlist_cap and len(filtered_pool) > shortlist_cap:
            ranked_pool = []
            for cand_key, block, block_meta in filtered_pool:
                same_item = bool(ref_meta.item and block_meta.item == ref_meta.item)
                code_relation = _code_relation(ref_meta.code, block_meta.code)
                unit_match = bool(ref_meta.unit and block_meta.unit and ref_meta.unit == block_meta.unit)
                value_close_loose = _value_close(ref_meta.valor_unit, block_meta.valor_unit, rel=0.25, abs_tol=1.0)
                quant_close_loose = _value_close(ref_meta.quant, block_meta.quant, rel=0.20, abs_tol=0.20)
                token_hits = len(ref_meta.tokens & block_meta.tokens) if ref_meta.tokens and block_meta.tokens else 0
                semantic_hits = len(ref_meta.semantic_tokens & block_meta.semantic_tokens) if ref_meta.semantic_tokens and block_meta.semantic_tokens else 0
                anchor_hits = len(ref_meta.anchors & block_meta.anchors) if ref_meta.anchors and block_meta.anchors else 0
                cheap_score = 0.0
                if same_item:
                    cheap_score += 8.0
                if code_relation == "exact":
                    cheap_score += 14.0
                elif code_relation in {"truncation", "near_typo"}:
                    cheap_score += 8.0
                if unit_match:
                    cheap_score += 3.0
                if value_close_loose:
                    cheap_score += 5.0
                if quant_close_loose:
                    cheap_score += 1.0
                cheap_score += min(token_hits, 4) * 1.2
                cheap_score += min(semantic_hits, 4) * 1.1
                cheap_score += min(anchor_hits, 3) * 0.8
                ranked_pool.append((cheap_score, cand_key, block, block_meta))
            ranked_pool.sort(key=lambda x: x[0], reverse=True)
            filtered_pool = [(cand_key, block, block_meta) for _, cand_key, block, block_meta in ranked_pool[:shortlist_cap]]

        candidates: List[tuple[float, str, BlocoComposicao, dict]] = []
        for cand_key, block, block_meta in filtered_pool:
            score, evidence = _block_match_score_from_meta(ref_meta, block, block_meta)
            strong_semantic = bool(
                evidence.get("valor_unit_close") and (
                    max(
                        float(evidence.get("desc_ratio", 0.0) or 0.0),
                        float(evidence.get("chargram_ratio", 0.0) or 0.0),
                        float(evidence.get("semantic_ratio", 0.0) or 0.0),
                    ) >= 0.44
                    or float(evidence.get("token_ratio", 0.0) or 0.0) >= 0.30
                    or float(evidence.get("anchor_ratio", 0.0) or 0.0) >= 0.24
                )
            )
            if (
                evidence.get("code_relation") == "divergent"
                and not evidence.get("unit_equal")
                and _clean(getattr(block, "item", "") or "") != ref_item
                and not (
                    evidence.get("valor_unit_close")
                    and float(evidence.get("desc_ratio", 0.0) or 0.0) >= 0.45
                    and float(evidence.get("anchor_ratio", 0.0) or 0.0) >= 0.25
                )
            ):
                continue
            if score < (20.0 if fast_mode else 18.0) and not strong_semantic:
                continue
            if max(evidence.get("desc_ratio", 0.0), evidence.get("chargram_ratio", 0.0), evidence.get("semantic_ratio", 0.0)) < (0.48 if fast_mode else 0.44) and not evidence.get("valor_unit_close") and _clean(getattr(block, "item", "") or "") != ref_item:
                continue
            candidates.append((score, cand_key, block, evidence))

        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates:
            best_score, best_key, best_block, best_evidence = candidates[0]
            second_score = candidates[1][0] if len(candidates) > 1 else -1.0
            if _should_accept_flexible_match(ref, best_score, second_score, best_evidence, best_block, fast_mode=fast_mode):
                target_block = principais.get(best_key)
                if target_block is None:
                    target_block = _clone_bloco(best_block)
                    principais[best_key] = target_block
                    candidate_blocks[best_key] = target_block
                if ref_item:
                    target_block.item = ref_item

                codigo_orc = _normalize_code_candidate(str(ref.get("codigo", "") or ""))
                codigo_comp = _normalize_code_candidate(str(target_block.principal.codigo or "") if target_block.principal else "")
                relation = {
                    "status": "associada_por_indicio",
                    "criterio": "matching_flexivel",
                    "item_orcamento": ref_item,
                    "ref_id_orcamento": ref_key,
                    "codigo_orcamento": codigo_orc,
                    "codigo_composicao_encontrado": codigo_comp,
                    "chave_bloco": best_key,
                    "score": round(best_score, 4),
                    "evidencia": best_evidence,
                    "divergencia_codigo": bool(codigo_orc and codigo_comp and codigo_orc != codigo_comp),
                }
                relation["suspeitas"] = _relation_suspeitas("associada_por_indicio", codigo_orc, codigo_comp, best_evidence)
                _append_orcamento_relation(target_block, relation)

                matched_items.add(ref_item)
                vinculados_flex.add(ref_item)
                if codigo_orc and codigo_comp and codigo_orc != codigo_comp:
                    avisos.append(
                        f"[composicoes] composição associada por indício ao item {ref_item}: bloco {best_key} (orçamento {ref_key}; divergência de código entre {codigo_orc} e {codigo_comp}; score={best_score:.2f})."
                    )
                else:
                    avisos.append(
                        f"[composicoes] composição associada por indício ao item {ref_item}: bloco {best_key} (orçamento {ref_key}; score={best_score:.2f})."
                    )
                continue

        if _likely_direct_item(ref, config=config):
            dispensados.add(_dispensa_ref_key(ref))
            avisos.append(
                f"[composicoes] dispensa de composição analítica para o item {ref_item} ({ref_key}): item direto/material detectado no orçamento."
            )

    return principais, dispensados, vinculados_flex

def _compute_missing_refs(orc_refs_all: List[dict], principais: Dict[str, BlocoComposicao], dispensados_refs: set[str], config: dict | None = None) -> List[str]:
    found_items = _associated_items_from_blocks(principais)
    found_ref_keys = set()
    for key, bloco in (principais or {}).items():
        found_ref_keys.add(key)
        principal = getattr(bloco, "principal", None)
        if principal is not None:
            principal_key = _normalize_ref_key(principal.codigo, principal.banco)
            if principal_key:
                found_ref_keys.add(principal_key)
        for rel in _iter_orcamento_relations(bloco):
            if str(rel.get("status") or "").strip() in _ASSOCIATED_RELATION_STATUSES:
                vinc_ref = _clean(rel.get("ref_id_orcamento") or "")
                vinc_item = _clean(rel.get("item_orcamento") or "")
                if vinc_ref:
                    found_ref_keys.add(vinc_ref)
                if vinc_item:
                    found_items.add(vinc_item)

    return sorted({
        str(ref.get("ref_id", "") or "")
        for ref in orc_refs_all
        if str(ref.get("ref_id", "") or "")
        and str(ref.get("item", "") or "") not in found_items
        and str(ref.get("ref_id", "") or "") not in found_ref_keys
        and _dispensa_ref_key(ref) not in dispensados_refs
        and not _likely_direct_item(ref, config=config)
    })

def _has_associated_relation(block: BlocoComposicao) -> bool:
    return any(
        str(rel.get("status") or "").strip() in _ASSOCIATED_RELATION_STATUSES
        for rel in _iter_orcamento_relations(block)
    )


def _clear_spurious_items_from_unassociated_blocks(principais: Dict[str, BlocoComposicao]) -> None:
    associated_items: Dict[str, list[str]] = {}
    for key, bloco in (principais or {}).items():
        item = _clean(getattr(bloco, "item", "") or "")
        if not item or not _has_associated_relation(bloco):
            continue
        associated_items.setdefault(item, []).append(key)

    for key, bloco in (principais or {}).items():
        item = _clean(getattr(bloco, "item", "") or "")
        if not item or _has_associated_relation(bloco):
            continue
        if item in associated_items and any(other_key != key for other_key in associated_items[item]):
            bloco.item = ""


def _is_structural_noise_block(block: RawBlock) -> bool:
    principal = getattr(block, "principal", None)
    if principal is None:
        return False
    desc = norm_text(str(getattr(principal, "descricao", "") or ""))
    code = _normalize_code_candidate(str(getattr(principal, "codigo", "") or ""))
    if not desc:
        return False
    header_like_patterns = [
        "composicoes analiticas com preco unitario",
        "composicoes analiticas com pre?co unitario",
        "bancos b d i",
        "encargos sociais",
    ]
    if "composicoes analiticas com preco unitario" in desc and "encargos sociais" in desc:
        return True
    if code and re.fullmatch(r"\d{6}", code) and "composicoes analiticas" in desc:
        return True
    return False




def _line_matches_sicro_section_row(line: LinhaComposicao, row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if _normalize_code_candidate(getattr(line, "codigo", "")) != _normalize_code_candidate(str(row.get("codigo") or "")):
        return False
    if _canon_bank(getattr(line, "banco", "")) != _canon_bank(str(row.get("banco") or "")):
        return False
    if _clean(getattr(line, "und", "")).upper() != _clean(str(row.get("und") or "")).upper():
        return False
    if _norm_desc_sig(getattr(line, "descricao", "")) != _norm_desc_sig(str(row.get("descricao") or "")):
        return False
    return True


def _dedup_sicro_auxiliares_against_sections(auxiliares: list[LinhaComposicao], detalhes: dict[str, Any]) -> list[LinhaComposicao]:
    sicro = dict((detalhes or {}).get("sicro") or {})
    secoes = dict(sicro.get("secoes") or {})
    sec_d = list(secoes.get("D") or [])
    if not sec_d:
        return auxiliares
    return [line for line in auxiliares if not any(_line_matches_sicro_section_row(line, row) for row in sec_d)]

def sanitize_composicoes_for_output(comp: Composicoes, *, include_tipo: bool | None = None) -> Composicoes:
    principais_out: Dict[str, BlocoComposicao] = {}
    for key, block in (comp.principais or {}).items():
        principal = _finalize_output_line(_clone_line(block.principal), include_tipo=include_tipo)
        detalhes = _clean_output_details(block.detalhes)
        auxiliares = [_finalize_output_line(_clone_line(x), include_tipo=include_tipo) for x in list(block.composicoes_auxiliares or [])]
        if _canon_bank(getattr(principal, "banco", "") or "") == "SICRO":
            auxiliares = _dedup_sicro_auxiliares_against_sections(auxiliares, detalhes)
        insumos = [LinhaInsumo(**_finalize_output_line(LinhaInsumo(**x.model_dump()), include_tipo=include_tipo).model_dump()) for x in list(block.insumos or [])]
        principais_out[key] = BlocoComposicao(
            item=str(getattr(block, "item", "") or ""),
            principal=principal,
            composicoes_auxiliares=auxiliares,
            insumos=insumos,
            pagina_inicio=(getattr(block, "page_start", 0) or getattr(block, "pagina_inicio", None) or (detalhes.get("pagina_inicio") if isinstance(detalhes, dict) else None) or None),
            pagina_fim=(getattr(block, "page_end", 0) or getattr(block, "pagina_fim", None) or (detalhes.get("pagina_fim") if isinstance(detalhes, dict) else None) or None),
            paginas=list(getattr(block, "pages_seen", []) or list(getattr(block, "paginas", []) or []) or list((detalhes.get("paginas") if isinstance(detalhes, dict) else []) or [])),
            detalhes=detalhes,
        )

    auxiliares_out: Dict[str, BlocoComposicao] = {}
    for key, block in (comp.auxiliares_globais or {}).items():
        principal = _finalize_output_line(_clone_line(block.principal), include_tipo=include_tipo)
        detalhes = _clean_output_details(block.detalhes)
        auxiliares = [_finalize_output_line(_clone_line(x), include_tipo=include_tipo) for x in list(block.composicoes_auxiliares or [])]
        if _canon_bank(getattr(principal, "banco", "") or "") == "SICRO":
            auxiliares = _dedup_sicro_auxiliares_against_sections(auxiliares, detalhes)
        insumos = [LinhaInsumo(**_finalize_output_line(LinhaInsumo(**x.model_dump()), include_tipo=include_tipo).model_dump()) for x in list(block.insumos or [])]
        auxiliares_out[key] = BlocoComposicao(
            item=str(getattr(block, "item", "") or ""),
            principal=principal,
            composicoes_auxiliares=auxiliares,
            insumos=insumos,
            pagina_inicio=(getattr(block, "page_start", 0) or getattr(block, "pagina_inicio", None) or (detalhes.get("pagina_inicio") if isinstance(detalhes, dict) else None) or None),
            pagina_fim=(getattr(block, "page_end", 0) or getattr(block, "pagina_fim", None) or (detalhes.get("pagina_fim") if isinstance(detalhes, dict) else None) or None),
            paginas=list(getattr(block, "pages_seen", []) or list(getattr(block, "paginas", []) or []) or list((detalhes.get("paginas") if isinstance(detalhes, dict) else []) or [])),
            detalhes=detalhes,
        )

    return Composicoes(
        principais=principais_out,
        auxiliares_globais=auxiliares_out,
        aliases_auxiliares=dict(comp.aliases_auxiliares or {}),
    )


def _build_block_truncation_aliases(blocks: Dict[str, RawBlock], orc_by_codebank: Dict[str, dict]) -> Dict[str, str]:
    groups: Dict[tuple[str, str, str, Optional[float]], List[str]] = {}
    for key, block in blocks.items():
        if block.principal is None:
            continue
        p = block.principal
        sig = (_canon_bank(p.banco), _norm_desc_sig(p.descricao), _clean(p.und).upper(), p.valor_unit)
        groups.setdefault(sig, []).append(key)

    aliases: Dict[str, str] = {}
    for keys in groups.values():
        if len(keys) < 2:
            continue
        ordered = sorted(
            keys,
            key=lambda k: (
                0 if k in orc_by_codebank else 1,
                0 if blocks[k].item else 1,
                -len(k.split("|", 1)[0]),
                k,
            ),
        )
        canonical = ordered[0]
        canonical_code = canonical.split("|", 1)[0] if "|" in canonical else canonical
        for candidate in ordered[1:]:
            cand_code = candidate.split("|", 1)[0] if "|" in candidate else candidate
            if _is_probable_truncation_variant(canonical_code, cand_code):
                aliases[candidate] = canonical
    return aliases


def _rewrite_aux_line_to_known_block(line: LinhaComposicao, known_blocks: Dict[str, RawBlock], aliases: Dict[str, str]) -> LinhaComposicao:
    ref_key = _normalize_ref_key(line.codigo, line.banco)
    target_key = aliases.get(ref_key, ref_key)
    if target_key and target_key in known_blocks:
        target = known_blocks[target_key].principal
        if target is not None:
            line.codigo = target.codigo
            line.banco = target.banco
            line.banco_coluna = target.banco_coluna or target.banco
        return line

    candidates: List[tuple[str, LinhaComposicao]] = []
    for key, block in known_blocks.items():
        if block.principal is None:
            continue
        principal = block.principal
        if _canon_bank(principal.banco) != _canon_bank(line.banco):
            continue
        if not _same_line_semantics(principal, line):
            continue
        if not _is_probable_truncation_variant(principal.codigo, line.codigo):
            continue
        candidates.append((key, principal))

    if len(candidates) == 1:
        _, principal = candidates[0]
        line.codigo = principal.codigo
        line.banco = principal.banco
        line.banco_coluna = principal.banco_coluna or principal.banco
    return line


def _materialize_missing_referenced_blocks(
    catalog: Dict[str, RawBlock],
    referenced_keys: Iterable[str],
    orphan_lines: Dict[str, LinhaComposicao],
) -> Dict[str, RawBlock]:
    for ref_key in referenced_keys or []:
        if not ref_key or ref_key in catalog or "|" not in ref_key:
            continue
        line = orphan_lines.get(ref_key)
        if line is None:
            continue
        catalog[ref_key] = RawBlock(item="", key=ref_key, principal=line, auxiliares=[], insumos=[])
    return catalog


def _looks_like_noise_text_line(line: str, dynamic_markers: List[str] | None = None) -> bool:
    up = _norm(line)
    if up.startswith((
        "ANEXO ",
        "ESTADO ",
        "GOVERNO ",
        "PREFEITURA ",
        "SECRETARIA ",
        "OBJETO:",
        "MUNICÍPIO:",
        "ENDEREÇO:",
        "DATA:",
        "ENC. SOCIAIS",
    )):
        return True
    return any(marker and marker.upper() in up for marker in (dynamic_markers or []))


def _split_text_segments(line: str) -> List[str]:
    clean_line = _clean(line)
    if not clean_line:
        return []
    if not RE_ROW_START_TEXT.match(clean_line):
        return [clean_line]

    split_points = [0]
    for match in RE_EMBEDDED_ROW_CAND.finditer(clean_line):
        idx = match.start()
        if idx <= 0:
            continue
        prefix = clean_line[:idx]
        if re.search(r"\d[\d\.,]*\s+\d[\d\.,]*\s+\d[\d\.,]*\s*$", prefix):
            split_points.append(idx)

    split_points = sorted(set(split_points))
    parts: List[str] = []
    for i, start in enumerate(split_points):
        end = split_points[i + 1] if i + 1 < len(split_points) else len(clean_line)
        part = clean_line[start:end].strip()
        if part:
            parts.append(part)
    return parts or [clean_line]


def _group_words_by_visual_line(words: List[dict], *, y_tolerance: float = 2.5) -> List[List[dict]]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (float(w.get("top", 0) or 0), float(w.get("x0", 0) or 0)))
    lines: List[List[dict]] = []
    current: List[dict] = []
    current_top: float | None = None
    for word in ordered:
        top = float(word.get("top", 0) or 0)
        if current and current_top is not None and abs(top - current_top) <= y_tolerance:
            current.append(word)
            current_top = ((current_top * (len(current) - 1)) + top) / len(current)
            continue
        if current:
            lines.append(sorted(current, key=lambda w: float(w.get("x0", 0) or 0)))
        current = [word]
        current_top = top
    if current:
        lines.append(sorted(current, key=lambda w: float(w.get("x0", 0) or 0)))
    return lines


def _words_line_text(line_words: List[dict]) -> str:
    return " ".join(_clean(w.get("text", "")) for w in line_words if _clean(w.get("text", ""))).strip()


def _header_aliases(runtime: dict | None, key: str, fallback: List[str]) -> List[str]:
    cfg = ((runtime or {}).get("header_cfg") or {}).get("aliases") or {}
    aliases = list(cfg.get(key) or [])
    if not aliases:
        aliases = list(fallback)
    return [str(alias) for alias in aliases if str(alias or "").strip()]


def _find_header_word_x(line_words: List[dict], *aliases: str) -> float | None:
    alias_norms = [norm_text(alias) for alias in aliases if alias]
    alias_norms = [alias for alias in alias_norms if alias]
    if not alias_norms:
        return None

    words = [word for word in line_words if _clean(word.get("text", ""))]
    word_norms = [norm_text(_clean(word.get("text", ""))) for word in words]

    multi_aliases = [alias for alias in alias_norms if len(alias.split()) > 1]
    for alias_norm in sorted(multi_aliases, key=lambda value: len(value.split()), reverse=True):
        parts = alias_norm.split()
        for idx in range(0, max(0, len(word_norms) - len(parts)) + 1):
            if word_norms[idx : idx + len(parts)] == parts:
                return float(words[idx].get("x0", 0) or 0)

    alias_set = set(alias_norms)
    for word, text_norm in zip(words, word_norms):
        if text_norm in alias_set:
            return float(word.get("x0", 0) or 0)

    fallback_aliases = [alias for alias in alias_norms if len(alias) >= 3]
    for word, text_norm in zip(words, word_norms):
        if not text_norm or len(text_norm) < 3:
            continue
        for alias in fallback_aliases:
            if text_norm.startswith(alias) or alias.startswith(text_norm):
                return float(word.get("x0", 0) or 0)
    return None


def _build_comp_header_layout(line_index: int, positions: dict[str, float], *, item_header: str = "") -> dict[str, Any]:
    ordered = sorted(((key, float(x)) for key, x in positions.items()), key=lambda pair: (pair[1], pair[0]))
    if not ordered:
        return {}

    columns: List[dict[str, Any]] = []
    text_like_fields = {"descricao", "tipo"}
    for idx, (key, x0) in enumerate(ordered):
        prev = ordered[idx - 1] if idx > 0 else None
        nxt = ordered[idx + 1] if idx + 1 < len(ordered) else None
        prev_mid = ((prev[1] + x0) / 2.0) if prev is not None else -1e9
        next_mid = ((x0 + nxt[1]) / 2.0) if nxt is not None else None

        left = prev_mid
        if key == "tipo":
            left = x0
        elif key == "descricao" and prev is not None and prev[0] == "tipo":
            left = x0

        right = next_mid
        if key in text_like_fields and nxt is not None:
            right = nxt[1]

        columns.append({
            "key": key,
            "x": x0,
            "left": left,
            "right": right,
        })

    label_cutoff = max(0.0, ordered[0][1] - 12.0)
    layout: dict[str, Any] = {
        "line_index": line_index,
        "item_header": item_header,
        "label_cutoff": label_cutoff,
        "columns": columns,
        "x_positions": {key: x for key, x in ordered},
    }
    for key, x0 in ordered:
        suffix = "valor" if key == "valor_unit" else key
        layout[f"x_{suffix}"] = x0
    return layout


def _detect_comp_header_positions_from_word_lines(lines: List[List[dict]], runtime: dict | None = None) -> dict[str, Any]:
    best_layout: dict[str, Any] = {}
    best_score = -1
    required = {"codigo", "banco", "descricao"}

    for idx, line_words in enumerate(lines):
        line_text = _words_line_text(line_words)
        if not line_text:
            continue

        positions: dict[str, float] = {}
        for key in _COMP_LAYOUT_FIELDS:
            aliases = _header_aliases(runtime, key, _DEFAULT_COMP_HEADER_ALIASES.get(key, []))
            x = _find_header_word_x(line_words, *aliases)
            if x is not None:
                positions[key] = float(x)

        if not required.issubset(set(positions)):
            continue
        if len(positions) < 6 and not line_has_header_markers(line_text, (runtime or {}).get("header_cfg"), required_keys=["codigo", "banco", "descricao"]):
            continue

        first_x = min(positions.values()) if positions else 0.0
        label_tokens = [
            _clean(w.get("text", ""))
            for w in line_words
            if float(w.get("x0", 0) or 0) < first_x and _clean(w.get("text", ""))
        ]
        item_header = next((tok for tok in label_tokens if _is_item_id(tok)), "")
        layout = _build_comp_header_layout(idx, positions, item_header=item_header)
        score = len(positions)
        if layout and score > best_score:
            best_layout = layout
            best_score = score
        if layout and positions.get("tipo") is not None and score >= 7:
            return layout
    return best_layout


def _structured_line_columns(line_words: List[dict], header_positions: dict[str, Any], *, docling_map: DoclingColumnMap | None = None) -> dict[str, str]:
    buckets: dict[str, List[str]] = {k: [] for k in ["label", "controle_linha", "codigo", "banco", "descricao", "tipo", "und", "quant", "valor", "total"]}

    def _bucket_key(field_key: str) -> str:
        if field_key == "controle_linha":
            return "label"
        return _COMP_CANONICAL_BUCKET_KEYS.get(field_key, field_key)

    # Primary v60 path: use Docling x-bands when available. Missing columns are
    # not fatal; the caller/legacy parser still handles whatever Docling did not
    # return (e.g. codigo in the provided composition schema).
    if docling_map is not None and docling_map.has_geometry:
        for word in line_words:
            text = _clean(word.get("text", ""))
            if not text:
                continue
            x0 = float(word.get("x0", 0) or 0)
            x1 = float(word.get("x1", x0) or x0)
            # v60.2: use assign_word rather than raw coordinate-only lookup so
            # the generic ColumnMergeResolver can route tokens from merged bands
            # (ex.: codigo+banco) by content evidence without hardcoded splits.
            canonical = docling_map.assign_word({"text": text, "x0": x0, "x1": x1}, mode="domain")
            if canonical is None:
                # Important: default ignores 'tipo' by coordinates so it cannot
                # contaminate descricao/und/values. Use raw mode only for debug.
                continue
            if canonical == "tipo" and not docling_map.include_tipo_in_final_json:
                continue
            if not docling_map.validate_field(canonical, text):
                continue
            buckets[_bucket_key(canonical)].append(text)
        # If Docling had no codigo band, keep the legacy label/code/header logic
        # available by merging only the non-empty Docling fields below.
        docling_result = {key: " ".join(values).strip() for key, values in buckets.items()}
        if any(docling_result.values()):
            legacy = _structured_line_columns(line_words, header_positions, docling_map=None)
            for key, value in docling_result.items():
                if value:
                    legacy[key] = value
            if docling_map.include_tipo_in_final_json and docling_result.get("tipo"):
                legacy["tipo"] = docling_result["tipo"]
            elif not docling_map.include_tipo_in_final_json:
                legacy["tipo"] = ""
            return legacy

    columns = list(header_positions.get("columns") or [])
    label_cutoff = float(header_positions.get("label_cutoff") or 0.0)
    for word in line_words:
        text = _clean(word.get("text", ""))
        if not text:
            continue
        x0 = float(word.get("x0", 0) or 0)
        if x0 < label_cutoff:
            buckets["label"].append(text)
            continue
        matched = False
        for column in columns:
            left = float(column.get("left", -1e9) or -1e9)
            right = column.get("right")
            right = float(right) if right is not None else None
            if x0 < left:
                continue
            if right is not None and x0 >= right:
                continue
            buckets[_bucket_key(str(column.get("key") or ""))].append(text)
            matched = True
            break
        if not matched and columns:
            last_key = _bucket_key(str(columns[-1].get("key") or ""))
            buckets[last_key].append(text)
    return {key: " ".join(values).strip() for key, values in buckets.items()}


def _kind_from_structured_label(label: str, runtime: dict | None = None) -> str:
    label_clean = _clean(label)
    if not label_clean:
        return ""
    detected = detect_composition_label(label_clean, (runtime or {}).get("config")) if runtime else ""
    if detected:
        return detected
    compact = norm_text(label_clean).replace(" ", "")
    if compact.startswith("insumo"):
        return "INSUMO"
    if "auxiliar" in compact and compact.startswith("compos"):
        return "AUXILIAR"
    if compact.startswith("compos"):
        return "COMPOSICAO"
    return ""


def _structured_row_is_noise(cols: dict[str, str], *, dynamic_markers: List[str] | None = None) -> bool:
    joined = _clean(" ".join(v for v in cols.values() if v))
    if not joined:
        return True
    if _looks_like_noise_text_line(joined, dynamic_markers=dynamic_markers):
        return True
    joined_norm = _norm(joined)
    return joined_norm.startswith(("MO SEM", "LS =>", "VALOR DO", "BDI =>"))


def _row_event_from_structured_acc(current: dict[str, List[str] | str], *, runtime: dict | None = None) -> dict[str, Any] | None:
    label = _clean(" ".join(current.get("label_parts", []) or []))
    kind = _kind_from_structured_label(label, runtime=runtime)
    code = _clean(current.get("codigo", ""))
    bank = _clean(current.get("banco", ""))
    if not kind or not code or not bank:
        return None
    desc = _clean(" ".join(current.get("descricao_parts", []) or []))
    tipo = _clean(" ".join(current.get("tipo_parts", []) or []))
    cells = [
        label,
        code,
        bank,
        desc,
        tipo,
        _clean(current.get("und", "")),
        _clean(current.get("quant", "")),
        _clean(current.get("valor", "")),
        _clean(current.get("total", "")),
    ]
    return {"event": "row", "kind": kind, "cells": cells}


def _extract_code_bank_from_text_line(line_text: str, *, runtime: dict | None = None) -> tuple[str, str]:
    tokens = _join_bank_tokens(_norm(line_text).split())
    bank = ""
    bank_idx = -1
    for i, token in enumerate(tokens):
        canon = _canon_bank(token, runtime=runtime)
        if canon in (_known_banks(runtime)):
            bank = canon
            bank_idx = i
            break
    code = _extract_joined_code(tokens, bank_idx) if bank_idx > 0 else ""
    return _normalize_code_candidate(code), bank


def _infer_tipo_header_and_bounds_from_lines(lines: List[List[dict]], *, runtime: dict | None = None, layout_hint: dict[str, Any] | None = None) -> tuple[int, float | None, float | None]:
    if layout_hint:
        try:
            hinted_tipo = layout_hint.get("x_tipo")
            hinted_und = layout_hint.get("x_und")
            if hinted_tipo is not None and hinted_und is not None and float(hinted_und) > float(hinted_tipo):
                header_idx = int(layout_hint.get("header_idx", -1) or -1)
                return header_idx, float(hinted_tipo), float(hinted_und)
        except Exception:
            pass
    header = _detect_comp_header_positions_from_word_lines(lines, runtime=runtime)
    if header:
        header_idx_raw = header.get("line_index", -1)
        header_idx = int(header_idx_raw) if header_idx_raw is not None else -1
        columns = list(header.get("columns") or [])
        tipo_col = next((col for col in columns if str(col.get("key") or "") == "tipo"), None)
        if header_idx >= 0 and tipo_col is not None:
            tipo_x = float(tipo_col.get("x", 0) or 0)
            tipo_left = float(tipo_col.get("left", tipo_x) or tipo_x)
            tipo_right_raw = tipo_col.get("right")
            tipo_right = float(tipo_right_raw) if tipo_right_raw is not None else None
            if tipo_right is None:
                follower_xs: List[float] = []
                for line_words in lines[header_idx + 1 : header_idx + 80]:
                    for word in line_words:
                        token = _clean(word.get("text", ""))
                        x0 = float(word.get("x0", 0) or 0)
                        if x0 <= tipo_x + 2:
                            continue
                        if _looks_like_unit_token(token) or RE_NUM.match(token):
                            follower_xs.append(x0)
                tipo_right = min(follower_xs) if follower_xs else tipo_x + 140.0
            return header_idx, max(tipo_left, tipo_x - 2.0), tipo_right

    for idx, line_words in enumerate(lines):
        x_codigo = _find_header_word_x(line_words, *_header_aliases(runtime, "codigo", _DEFAULT_COMP_HEADER_ALIASES["codigo"]))
        x_tipo = _find_header_word_x(line_words, *_header_aliases(runtime, "tipo", _DEFAULT_COMP_HEADER_ALIASES["tipo"]))
        if x_codigo is None or x_tipo is None:
            continue
        follower_xs: List[float] = []
        for later_words in lines[idx + 1 : idx + 80]:
            for word in later_words:
                token = _clean(word.get("text", ""))
                x0 = float(word.get("x0", 0) or 0)
                if x0 <= float(x_tipo) + 2:
                    continue
                if _looks_like_unit_token(token) or RE_NUM.match(token):
                    follower_xs.append(x0)
        tipo_right = min(follower_xs) if follower_xs else float(x_tipo) + 140.0
        return idx, float(x_tipo) - 2.0, tipo_right

    return -1, None, None


def _collect_tipo_entries_from_positioned_fragments(
    fragments: List[dict],
    *,
    runtime: dict | None = None,
    dynamic_markers: List[str] | None = None,
    layout_hint: dict[str, Any] | None = None,
    return_layout: bool = False,
) -> List[dict[str, str]] | tuple[List[dict[str, str]], dict[str, Any]]:
    words: List[dict] = []
    for frag in fragments or []:
        token = _clean(frag.get("text", ""))
        x0 = float(frag.get("x0", 0) or 0)
        top = float(frag.get("top", 0) or 0)
        if not token or x0 <= 0 or top <= 0:
            continue
        words.append({"text": token, "x0": x0, "top": top})
    if not words:
        return []

    lines = _group_words_by_visual_line(words, y_tolerance=3.2)
    if not lines:
        return []

    header_idx, x_tipo, x_und = _infer_tipo_header_and_bounds_from_lines(lines, runtime=runtime, layout_hint=layout_hint)
    if header_idx < 0 or x_tipo is None or x_und is None or x_und <= x_tipo:
        return ([], {}) if return_layout else []

    row_starts: List[tuple[int, str, str, str]] = []
    for idx, line_words in enumerate(lines[header_idx + 1 :], start=header_idx + 1):
        line_text = _words_line_text(line_words)
        if not line_text:
            continue
        compact = norm_text(line_text).replace(" ", "")
        if not (compact.startswith("compos") or compact.startswith("insumo")):
            continue
        code, bank = _extract_code_bank_from_text_line(line_text, runtime=runtime)
        row_starts.append((idx, code, bank, line_text))

    entries: List[dict[str, str]] = []
    for pos, (start_idx, code, bank, _line_text) in enumerate(row_starts):
        end_idx = row_starts[pos + 1][0] - 1 if pos + 1 < len(row_starts) else len(lines) - 1
        tipo_parts: List[str] = []
        for line_words in lines[start_idx : end_idx + 1]:
            line_text = _words_line_text(line_words)
            if not line_text or _looks_like_noise_text_line(line_text, dynamic_markers=dynamic_markers):
                continue
            line_norm = _norm(line_text)
            if line_norm.startswith(("MO SEM", "LS =>", "VALOR DO", "VALOR COM BDI", "BDI =>")):
                continue
            band_words = [
                _clean(word.get("text", ""))
                for word in line_words
                if x_tipo - 2 <= float(word.get("x0", 0) or 0) < x_und - 1 and _clean(word.get("text", ""))
            ]
            if not band_words:
                continue
            band_text = _clean(" ".join(band_words))
            if not band_text or _normalized_upper(band_text) == "TIPO":
                continue
            tipo_parts.append(band_text)

        raw_tipo = _clean(" ".join(tipo_parts))
        tipo = _normalize_output_tipo(raw_tipo, bank=bank) if raw_tipo else ""
        entries.append({
            "codigo": _normalize_code_candidate(code),
            "banco": _canon_bank(bank, runtime=runtime),
            "tipo": tipo,
        })
    layout = {"header_idx": header_idx, "x_tipo": float(x_tipo), "x_und": float(x_und)}
    return (entries, layout) if return_layout else entries


def _collect_tipo_candidates_from_positioned_fragments(
    fragments: List[dict],
    *,
    runtime: dict | None = None,
    dynamic_markers: List[str] | None = None,
    layout_hint: dict[str, Any] | None = None,
) -> Dict[str, str]:
    candidates: Dict[str, str] = {}
    for entry in _collect_tipo_entries_from_positioned_fragments(
        fragments,
        runtime=runtime,
        dynamic_markers=dynamic_markers,
        layout_hint=layout_hint,
    ):
        codigo = str(entry.get("codigo") or "")
        banco = str(entry.get("banco") or "")
        tipo = str(entry.get("tipo") or "")
        if not codigo or not banco or not tipo:
            continue
        _register_tipo_candidate(candidates, codigo, banco, tipo)
    return candidates


def _collect_tipo_entries_from_pypdf_page(
    page_no: int,
    *,
    pdf_session: PdfDocumentSession | None = None,
    runtime: dict | None = None,
    dynamic_markers: List[str] | None = None,
    layout_hint: dict[str, Any] | None = None,
    return_layout: bool = False,
) -> List[dict[str, str]] | tuple[List[dict[str, str]], dict[str, Any]]:
    if pdf_session is None:
        return []
    fragments = pdf_session.get_text_fragments(page_no)
    return _collect_tipo_entries_from_positioned_fragments(
        fragments,
        runtime=runtime,
        dynamic_markers=dynamic_markers,
        layout_hint=layout_hint,
        return_layout=return_layout,
    )


def _collect_tipo_candidates_from_pypdf_page(
    page_no: int,
    *,
    pdf_session: PdfDocumentSession | None = None,
    runtime: dict | None = None,
    dynamic_markers: List[str] | None = None,
    layout_hint: dict[str, Any] | None = None,
) -> Dict[str, str]:
    if pdf_session is None:
        return {}
    fragments = pdf_session.get_text_fragments(page_no)
    return _collect_tipo_candidates_from_positioned_fragments(
        fragments,
        runtime=runtime,
        dynamic_markers=dynamic_markers,
        layout_hint=layout_hint,
    )


def _page_profile_entry(page_plan: dict[str, Any] | None, page_no: int) -> dict[str, Any]:
    profiles = ((page_plan or {}).get("page_profiles") or {}) if page_plan else {}
    entry = profiles.get(page_no)
    return dict(entry) if isinstance(entry, dict) else {}


def _page_block_entry(page_plan: dict[str, Any] | None, page_no: int) -> dict[str, Any]:
    if not page_plan:
        return {}
    profile = _page_profile_entry(page_plan, page_no)
    block_id = str(profile.get("block_id") or "")
    blocks_by_id = (page_plan.get("blocks_by_id") or {}) if isinstance(page_plan, dict) else {}
    block = blocks_by_id.get(block_id)
    return block if isinstance(block, dict) else {}


def _should_prefer_standard_page_parser(page_profile: dict[str, Any] | None, config: dict | None = None) -> bool:
    profile = page_profile or {}
    if not _is_fast_profile(config):
        return False
    if bool(profile.get("pure_sicro")) or bool(profile.get("dedicated_sicro")):
        return False

    effort = str(profile.get("effort") or "light")
    template_source = str(profile.get("template_source") or "")
    regime = str(profile.get("regime") or "generic")
    tipo_candidate = bool(profile.get("tipo_candidate"))
    tipo_header_hits = int(profile.get("tipo_header_hits") or 0)
    tipo_value_hits = int(profile.get("tipo_value_hits") or 0)

    if template_source == "standard":
        if effort != "heavy":
            return True
        if regime in {"sinapi_like", "orse_like", "proprio_like", "generic"} and not tipo_candidate:
            return True
        if regime in {"sinapi_like", "orse_like", "proprio_like", "generic"} and tipo_candidate and tipo_header_hits <= 0 and tipo_value_hits < 3:
            return True
        return False

    return effort == "light" and not tipo_candidate


def _line_starts_sicro_section(line_text: str) -> bool:
    clean = _clean(line_text)
    if not clean:
        return False
    for patterns in _SICRO_SECTION_REGEXES.values():
        if any(pattern.search(clean) for pattern in patterns):
            return True
    line_norm = _norm(clean)
    return line_norm.startswith((
        "CUSTO DO FIC",
        "PRODUCAO DE EQUIPE",
        "PRODUÇÃO DE EQUIPE",
        "CUSTO UNITARIO DE EXECUCAO",
        "CUSTO UNITÁRIO DE EXECUÇÃO",
        "TEMPO FIXO",
        "MOMENTO DE TRANSPORTE",
    ))


def _should_collect_page_tipo_entries(
    *,
    page_profile: dict[str, Any] | None,
    missing_tipo_rows: int,
    rows_seen: int,
    layered_mode: bool,
    tipo_recovery_mode: str,
) -> bool:
    if tipo_recovery_mode in {"disabled", "api_only"}:
        return False
    if rows_seen <= 0:
        return False
    profile = page_profile or {}
    if bool(profile.get("pure_sicro")) or bool(profile.get("dedicated_sicro")) or not bool(profile.get("tipo_expected", True)):
        return False

    template_source = str(profile.get("template_source") or "")
    effort = str(profile.get("effort") or "light")
    tipo_candidate = bool(profile.get("tipo_candidate"))
    tipo_header_hits = int(profile.get("tipo_header_hits") or 0)
    tipo_value_hits = int(profile.get("tipo_value_hits") or 0)
    strong_tipo_signal = tipo_candidate and (tipo_header_hits > 0 or tipo_value_hits >= 3)
    strong_standard_tipo_signal = tipo_candidate and tipo_value_hits >= 3 and tipo_header_hits > 0

    if tipo_recovery_mode == "eager":
        if template_source == "standard":
            if effort not in {"standard", "heavy"}:
                return False
            if not strong_standard_tipo_signal:
                return False
        return True

    if missing_tipo_rows <= 0:
        return False

    if template_source == "standard":
        if not strong_standard_tipo_signal:
            return False
        if effort == "light":
            return False
        if missing_tipo_rows >= 3:
            return True
        if missing_tipo_rows >= 2 and effort in {"standard", "heavy"} and tipo_header_hits > 0:
            return True
        return False

    if template_source != "standard":
        if tipo_candidate and (effort in {"standard", "heavy"} or not layered_mode):
            return True
    elif effort == "heavy" and tipo_candidate:
        return True
    if not layered_mode and tipo_candidate and missing_tipo_rows >= 2:
        return True
    return False


def _session_has_pdfplumber(pdf_session: PdfDocumentSession | None) -> bool:
    if pdf_session is None:
        return pdfplumber is not None
    return bool(getattr(pdf_session, "has_pdfplumber", pdfplumber is not None))


def _extract_structured_text_events_from_page(page_no: int, *, pdf_session: PdfDocumentSession | None = None, runtime: dict | None = None, dynamic_markers: List[str] | None = None, docling_map: DoclingColumnMap | None = None) -> List[dict[str, Any]]:
    """Extract structured row events from positioned words.

    v60.1 long-composition fix:
    - If a real header is found in the middle/end of a page, rows before that
      header are still parsed using the same column layout and are treated as
      continuation rows of the currently open block.
    - If no real header is found, the Docling column map is used as inherited
      layout without emitting a fake item header from the seed page.
    """
    if pdf_session is None or not _session_has_pdfplumber(pdf_session):
        return []
    words = pdf_session.get_words(page_no)
    if not words:
        return []
    lines = _group_words_by_visual_line(words)
    detected_header = _detect_comp_header_positions_from_word_lines(lines, runtime=runtime)
    docling_header = docling_map.header_layout() if docling_map is not None and docling_map.has_geometry else None
    if not detected_header and not docling_header:
        return []

    events: List[dict[str, Any]] = []

    def _consume_line_range(header_layout: dict[str, Any], start_idx: int, end_idx: int | None, *, allow_item_headers: bool) -> List[dict[str, Any]]:
        local_events: List[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        stop_idx = len(lines) if end_idx is None else max(0, min(end_idx, len(lines)))

        def _flush_current() -> None:
            nonlocal current
            if current:
                event = _row_event_from_structured_acc(current, runtime=runtime)
                if event:
                    local_events.append(event)
            current = None

        for idx, line_words in enumerate(lines[max(0, start_idx):stop_idx], start=max(0, start_idx)):
            cols = _structured_line_columns(line_words, header_layout, docling_map=docling_map)
            joined = _clean(" ".join(v for v in cols.values() if v))
            if not joined:
                continue

            if allow_item_headers and line_has_header_markers(joined, (runtime or {}).get("header_cfg"), required_keys=["codigo", "banco"]) and _is_item_id(cols.get("label", "")):
                _flush_current()
                local_events.append({"event": "item_header", "item": _clean(cols.get("label", ""))})
                continue

            if line_has_header_markers(joined, (runtime or {}).get("header_cfg"), required_keys=["codigo", "banco"]):
                continue

            if _structured_row_is_noise(cols, dynamic_markers=dynamic_markers):
                continue

            has_code_bank = bool(cols.get("codigo") and cols.get("banco"))
            kind = _kind_from_structured_label(cols.get("label", ""), runtime=runtime)
            starts_row = has_code_bank and bool(kind)

            if starts_row:
                _flush_current()
                current = {
                    "label_parts": [cols.get("label", "")],
                    "codigo": cols.get("codigo", ""),
                    "banco": cols.get("banco", ""),
                    "descricao_parts": [cols.get("descricao", "")] if cols.get("descricao") else [],
                    "tipo_parts": [cols.get("tipo", "")] if cols.get("tipo") else [],
                    "und": cols.get("und", ""),
                    "quant": cols.get("quant", ""),
                    "valor": cols.get("valor", ""),
                    "total": cols.get("total", ""),
                }
                continue

            if current is None:
                continue

            if cols.get("codigo") or cols.get("banco"):
                _flush_current()
                continue

            continuation_payload = cols.get("descricao") or cols.get("tipo") or cols.get("label")
            if not continuation_payload:
                continue
            if cols.get("label"):
                current.setdefault("label_parts", []).append(cols.get("label", ""))
            if cols.get("descricao"):
                current.setdefault("descricao_parts", []).append(cols.get("descricao", ""))
            if cols.get("tipo"):
                current.setdefault("tipo_parts", []).append(cols.get("tipo", ""))

        _flush_current()
        return local_events

    if detected_header:
        header_idx = int(detected_header.get("line_index") or 0)
        if header_idx > 0:
            events.extend(_consume_line_range(detected_header, 0, header_idx, allow_item_headers=False))

        item_header = _clean(detected_header.get("item_header", ""))
        if item_header:
            events.append({"event": "item_header", "item": item_header})

        events.extend(_consume_line_range(detected_header, header_idx + 1, None, allow_item_headers=True))
        return events

    events.extend(_consume_line_range(docling_header or {}, 0, None, allow_item_headers=True))
    return events


def _parse_text_row(start_text: str, continuations: List[str], dynamic_markers: List[str] | None = None, runtime: dict | None = None, *, finalize_text: bool = True) -> Optional[Tuple[str, LinhaComposicao]]:
    start_text = _clean(start_text)
    continuations = [_clean(c) for c in continuations if _clean(c)]
    if not start_text or _looks_like_text_section_heading(start_text):
        return None

    assembled = start_text
    consumed = 0
    while consumed < len(continuations):
        has_tail = RE_TAIL_VALUES_TEXT.search(assembled) is not None
        has_bank = any(_canon_bank(tok, runtime=runtime) in (_known_banks(runtime)) for tok in _join_bank_tokens(_norm(assembled).split()))
        if has_tail and has_bank:
            break
        assembled = _clean(f"{assembled} {continuations[consumed]}")
        consumed += 1
    remaining_conts = continuations[consumed:]

    assembled_up = _norm(assembled)
    detected_kind = detect_composition_label(assembled_up, (runtime or {}).get("config")) if runtime else ""
    if detected_kind:
        kind = detected_kind
    elif assembled_up.startswith("INSUMO"):
        kind = "INSUMO"
    else:
        kind = "AUXILIAR" if re.match(r"^COMPOSI(?:[ÇC][AÃ]O?)?\s+.*\bAUXILIAR\b", assembled_up) else "COMPOSICAO"

    m = re.match(r"^(Insumo|Composi(?:[çc][aã]o?)?)\s*(.*)$", assembled, re.IGNORECASE)
    rest = _clean(m.group(2) if m else assembled)
    rest = re.sub(r"(?i)^o\s+Auxiliar\b(?!\s+de\b)", "", rest).strip()
    rest = re.sub(r"(?i)^Auxiliar\b(?!\s+de\b)", "", rest).strip()
    tokens = _join_bank_tokens(rest.upper().split())

    bank = ""
    bank_token = ""
    bank_idx = -1
    for i, token in enumerate(tokens):
        canon = _canon_bank(token, runtime=runtime)
        if canon in (_known_banks(runtime)):
            bank = canon
            bank_token = token
            bank_idx = i
            break

    code = ""
    if bank_idx > 0:
        code = _extract_joined_code(tokens, bank_idx)
    elif bank_idx == 0:
        for cont in remaining_conts:
            parts = re.findall(r"[0-9A-Z_]+", cont.upper())
            if not parts:
                continue
            candidate = _extract_joined_code(parts, len(parts))
            if candidate and candidate.upper() != "AUXILIAR":
                code = _normalize_code_candidate(candidate)
                break

    tail_info = _choose_tail_candidate_from_text(assembled)
    selected_tail = dict(tail_info.get("selected") or {})
    und = str(selected_tail.get("und") or "")
    quant = selected_tail.get("quant")
    valor_unit = selected_tail.get("valor_unit")
    total = selected_tail.get("total")
    tail_match = RE_TAIL_VALUES_TEXT.search(assembled)
    prefix = assembled
    if tail_match:
        und = und or tail_match.group("und")
        quant = quant if quant is not None else parse_ptbr_number(tail_match.group("quant"))
        valor_unit = valor_unit if valor_unit is not None else parse_ptbr_number(tail_match.group("valor"))
        total = total if total is not None else parse_ptbr_number(tail_match.group("total"))
        prefix = assembled[: tail_match.start()].strip()
    elif selected_tail.get("raw_fragment"):
        prefix = _strip_tail_fragment(assembled, str(selected_tail.get("raw_fragment") or ""))

    prefix = re.sub(r"^(Insumo|Composi(?:[çc][aã]o?)?)\s*", "", prefix, flags=re.IGNORECASE).strip()
    prefix = re.sub(r"(?i)^o\s+Auxiliar\b(?!\s+de\b)", "", prefix).strip()
    prefix = re.sub(r"(?i)^Auxiliar\b(?!\s+de\b)", "", prefix).strip()
    if bank_token:
        prefix = re.sub(rf"^(?:{re.escape(code)}\s+)?{re.escape(bank_token)}\s*", "", prefix, count=1, flags=re.IGNORECASE).strip()
    elif code:
        prefix = re.sub(rf"^{re.escape(code)}\s*", "", prefix, count=1, flags=re.IGNORECASE).strip()

    extras: List[str] = []
    for cont in remaining_conts:
        part = cont
        part = re.sub(r"^o\s+Auxiliar\b(?!\s+de\b)", "", part, flags=re.IGNORECASE).strip()
        part = re.sub(r"^Auxiliar\b(?!\s+de\b)", "", part, flags=re.IGNORECASE).strip()
        if code:
            part = re.sub(rf"^o\s+{re.escape(code)}\b", "", part, count=1, flags=re.IGNORECASE).strip()
        else:
            part = re.sub(r"^o\b", "", part, count=1, flags=re.IGNORECASE).strip()
        if not part:
            continue
        up = _norm(part)
        if up.startswith(("MO SEM", "LS =>", "VALOR DO", "BDI =>")):
            continue
        extras.append(part)

    raw_desc = re.sub(r"\s+", " ", " ".join([prefix] + extras)).strip()
    descricao = _sanitize_description(raw_desc, code=code, bank=bank, dynamic_markers=dynamic_markers) if finalize_text else _lightweight_clean_description(raw_desc, code=code, bank=bank)
    line = LinhaComposicao(
        codigo=_normalize_code_candidate(code),
        banco=_canon_bank(bank, runtime=runtime),
        descricao=descricao,
        natureza=_structural_nature(kind),
        tipo="",
        und=und,
        quant=quant,
        valor_unit=valor_unit,
        total=total,
        banco_coluna=_canon_bank(bank, runtime=runtime),
    )
    if tail_info.get("status") not in {"consistent", "missing"}:
        line.detalhes["tail_parse"] = _tail_info_payload(tail_info)
    return kind, line
def _extract_blocks_from_text(
    pdf_bytes: bytes,
    start_1based: int,
    end_1based: int,
    context: dict | None = None,
    config: dict | None = None,
    *,
    page_texts: List[str] | None = None,
    page_numbers: List[int] | None = None,
    pdf_session: PdfDocumentSession | None = None,
    finalize_text: bool = True,
    tipo_candidates: Dict[str, str] | None = None,
    page_plan: dict[str, Any] | None = None,
) -> Dict[str, RawBlock]:
    blocks: Dict[str, RawBlock] = {}
    dynamic_markers = build_dynamic_markers(context or {})
    runtime = _runtime_rules(config)
    docling_map = DoclingColumnMap.from_context(context or {}, config=config, family="composition")
    include_tipo_final = _include_tipo_in_final_json(config, context)
    pending_item = ""
    current_block: Optional[RawBlock] = None
    current_row_start: str = ""
    current_conts: List[str] = []
    current_page = start_1based
    current_page_use_standard = False
    current_page_tipo_entries: List[dict[str, str]] = []
    current_page_tipo_idx = 0
    current_page_rows_seen = 0
    current_page_missing_tipo_rows = 0
    block_templates = (page_plan or {}).get("blocks_by_id") if isinstance(page_plan, dict) else {}
    metrics = ((page_plan or {}).get("metrics") or {}) if isinstance(page_plan, dict) else {}
    metric_block_sets: dict[str, set[str]] = {
        "standard_block_hits": set(),
        "heavy_block_parses": set(),
        "heavy_block_successes": set(),
        "tipo_recovery_block_hits": set(),
    }
    metric_section_sets: dict[str, set[str]] = {
        "sicro_section_standard_hits": set(),
        "sicro_section_template_hits": set(),
    }
    if isinstance(metrics, dict):
        metrics.setdefault("standard_page_fast_path_hits", 0)
        metrics.setdefault("structured_page_parses", 0)
        metrics.setdefault("eager_tipo_pages", 0)
        metrics.setdefault("on_demand_tipo_pages", 0)
        metrics.setdefault("sicro_section_skip_lines", 0)
        metrics.setdefault("standard_block_hits", 0)
        metrics.setdefault("standard_block_failures", 0)
        metrics.setdefault("local_template_hits", 0)
        metrics.setdefault("local_template_creations", 0)
        metrics.setdefault("heavy_block_parses", 0)
        metrics.setdefault("heavy_block_successes", 0)
        metrics.setdefault("sicro_section_standard_hits", 0)
        metrics.setdefault("sicro_section_template_hits", 0)
        metrics.setdefault("tipo_recovery_block_hits", 0)
        metrics.setdefault("page_reparse_count", 0)
        metrics.setdefault("sicro_doc_profile_hits", 0)

    def _metric_block_hit(metric_name: str, page_no: int) -> None:
        if not isinstance(metrics, dict):
            return
        profile = _page_profile_entry(page_plan, page_no)
        block_id = str(profile.get("block_id") or "")
        if not block_id:
            return
        bucket = metric_block_sets.get(metric_name)
        if bucket is None:
            return
        if block_id in bucket:
            return
        bucket.add(block_id)
        metrics[metric_name] = int(metrics.get(metric_name) or 0) + 1

    def _metric_section_hit(metric_name: str, page_no: int) -> None:
        if not isinstance(metrics, dict):
            return
        profile = _page_profile_entry(page_plan, page_no)
        sections = list(profile.get("known_sicro_templates") or [])
        if not sections:
            return
        for section in sections:
            key = f"{page_no}:{section}"
            bucket = metric_section_sets.get(metric_name)
            if bucket is None or key in bucket:
                continue
            bucket.add(key)
            metrics[metric_name] = int(metrics.get(metric_name) or 0) + 1

    def _block_tipo_layout_hint(page_no: int) -> dict[str, Any] | None:
        block = _page_block_entry(page_plan, page_no)
        layout = block.get("tipo_layout") if isinstance(block, dict) else None
        return dict(layout) if isinstance(layout, dict) else None

    def _remember_block_tipo_layout(page_no: int, layout: dict[str, Any] | None) -> None:
        if not layout or not isinstance(block_templates, dict):
            return
        profile = _page_profile_entry(page_plan, page_no)
        block_id = str(profile.get("block_id") or "")
        if not block_id:
            return
        block = block_templates.get(block_id)
        if not isinstance(block, dict):
            return
        if not isinstance(block.get("tipo_layout"), dict):
            block["tipo_layout"] = dict(layout)
    layered_mode = _resolve_interval_processing_mode(config) == "layered"
    tipo_recovery_mode = _resolve_tipo_recovery_mode(config)
    if not include_tipo_final:
        tipo_recovery_mode = "disabled"

    def commit_current_block(reason: str = "commit") -> None:
        nonlocal current_block
        if current_block and current_block.principal and current_block.key:
            parent_key = _normalize_ref_key(current_block.principal.codigo, current_block.principal.banco)
            current_block.key = parent_key or current_block.key
            current_block.auxiliares = _dedup_auxiliares(current_block.auxiliares, parent_key=current_block.key)
            current_block.insumos = [LinhaInsumo(**x.model_dump()) for x in _dedup_lines(current_block.insumos)]
            _mark_block_closure(current_block, reason, page_no=current_page)
            current_block.detalhes["status_completude"] = "completo" if current_block.insumos or current_block.auxiliares else "sem_componentes"
            blocks[current_block.key] = current_block
        current_block = None

    def start_new_block(line: LinhaComposicao, item_value: str = "") -> None:
        nonlocal current_block, pending_item
        provisional_key = (
            f"{line.codigo}|{line.banco}"
            if line.codigo and line.banco
            else _make_recovery_key(item_value, line.banco)
        )
        if not provisional_key:
            current_block = None
            return
        current_block = RawBlock(
            item=item_value,
            key=provisional_key,
            principal=line,
            page=current_page,
            page_start=current_page,
            page_end=current_page,
            pages_seen=[current_page],
            detalhes={"origens_extracao": ["text"]},
        )
        _touch_block_page(current_block, current_page, source="text")
        if item_value and pending_item == item_value:
            pending_item = ""

    def process_parsed_row(kind: str, line: LinhaComposicao) -> None:
        nonlocal current_block, pending_item, current_page_rows_seen, current_page_missing_tipo_rows, current_page_use_standard
        if kind in {"COMPOSICAO", "AUXILIAR", "INSUMO"}:
            current_page_rows_seen += 1
            if not current_page_use_standard:
                _metric_block_hit("heavy_block_successes", current_page)
            if _canon_bank(getattr(line, "banco", "") or "", runtime=runtime) != "SICRO" and not _clean(getattr(line, "tipo", "") or "") and _clean(getattr(line, "codigo", "") or "") and _clean(getattr(line, "banco", "") or ""):
                current_page_missing_tipo_rows += 1

        if kind == "COMPOSICAO":
            item_value = pending_item if pending_item else ""
            incoming_key = _normalize_ref_key(line.codigo, line.banco)
            current_key = ""
            if current_block is not None and current_block.principal is not None:
                current_key = _normalize_ref_key(current_block.principal.codigo, current_block.principal.banco)

            if current_block is None or current_block.principal is None:
                start_new_block(line, item_value=item_value)
                return

            if incoming_key and incoming_key == current_key:
                current_block.principal = _merge_line(current_block.principal, line)
                _touch_block_page(current_block, current_page, source="text")
                if item_value and not current_block.item:
                    current_block.item = item_value
                    if pending_item == item_value:
                        pending_item = ""
                return

            commit_current_block("nova_composicao_textual")
            start_new_block(line, item_value=item_value)
            return

        if current_block is None or current_block.principal is None:
            return

        if kind == "AUXILIAR":
            if line.codigo and line.banco:
                current_block.auxiliares.append(line)
                _touch_block_page(current_block, current_page, source="text")
            return

        if kind == "INSUMO":
            if line.codigo and line.banco:
                current_block.insumos.append(LinhaInsumo(**line.model_dump()))
                _touch_block_page(current_block, current_page, source="text")
            return

    def flush_row() -> None:
        nonlocal current_row_start, current_conts, current_page_tipo_idx
        if not current_row_start:
            return
        parsed = _parse_text_row(current_row_start, current_conts, dynamic_markers=dynamic_markers, runtime=runtime, finalize_text=finalize_text)
        current_row_start = ""
        current_conts = []
        if not parsed:
            return
        kind, line = parsed
        if _canon_bank(getattr(line, "banco", "") or "", runtime=runtime) != "SICRO" and current_page_tipo_idx < len(current_page_tipo_entries):
            entry = current_page_tipo_entries[current_page_tipo_idx]
            current_page_tipo_idx += 1
            candidate_tipo = str(entry.get("tipo") or "")
            if candidate_tipo and not _clean(getattr(line, "tipo", "") or ""):
                line.tipo = candidate_tipo
                _register_tipo_candidate(
                    tipo_candidates or {},
                    str(getattr(line, "codigo", "") or entry.get("codigo") or ""),
                    str(getattr(line, "banco", "") or entry.get("banco") or ""),
                    candidate_tipo,
                )
        process_parsed_row(kind, line)

    def flush_block() -> None:
        flush_row()
        commit_current_block("fim_intervalo_textual")

    def finalize_page_tipo_recovery(page_no: int) -> None:
        nonlocal current_page_tipo_entries, current_page_tipo_idx, current_page_rows_seen, current_page_missing_tipo_rows
        if tipo_candidates is None or pdf_session is None or _session_has_pdfplumber(pdf_session):
            current_page_tipo_entries = []
            current_page_tipo_idx = 0
            current_page_rows_seen = 0
            current_page_missing_tipo_rows = 0
            return
        page_profile = _page_profile_entry(page_plan, page_no)
        should_collect = _should_collect_page_tipo_entries(
            page_profile=page_profile,
            missing_tipo_rows=current_page_missing_tipo_rows,
            rows_seen=current_page_rows_seen,
            layered_mode=layered_mode,
            tipo_recovery_mode=tipo_recovery_mode,
        )
        if should_collect and not current_page_tipo_entries:
            if isinstance(metrics, dict):
                metrics["on_demand_tipo_pages"] = int(metrics.get("on_demand_tipo_pages") or 0) + 1
            _metric_block_hit("tipo_recovery_block_hits", page_no)
            collected = _collect_tipo_entries_from_pypdf_page(
                page_no,
                pdf_session=pdf_session,
                runtime=runtime,
                dynamic_markers=dynamic_markers,
                layout_hint=_block_tipo_layout_hint(page_no),
                return_layout=True,
            )
            current_page_tipo_entries, learned_layout = collected if isinstance(collected, tuple) else (list(collected or []), {})
            _remember_block_tipo_layout(page_no, learned_layout)
            for entry in current_page_tipo_entries:
                codigo_candidate = str(entry.get("codigo") or "")
                banco_candidate = str(entry.get("banco") or "")
                candidate_tipo = str(entry.get("tipo") or "")
                if codigo_candidate and banco_candidate and candidate_tipo:
                    _register_tipo_candidate(tipo_candidates, codigo_candidate, banco_candidate, candidate_tipo)
        current_page_tipo_entries = []
        current_page_tipo_idx = 0
        current_page_rows_seen = 0
        current_page_missing_tipo_rows = 0

    if page_texts is None:
        if pdf_session is not None:
            page_texts = pdf_session.get_page_texts(start_1based, end_1based, engine="pypdf")
        else:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            max_page = min(end_1based, len(reader.pages))
            page_texts = [reader.pages[page_no - 1].extract_text() or "" for page_no in range(max(1, start_1based), max_page + 1)]

    resolved_page_numbers = list(page_numbers or [])
    previous_page_no: int | None = None
    for offset, page_text in enumerate(page_texts):
        current_page = resolved_page_numbers[offset] if offset < len(resolved_page_numbers) else start_1based + offset
        if previous_page_no is not None:
            finalize_page_tipo_recovery(previous_page_no)
        previous_page_no = current_page
        current_page_tipo_entries = []
        current_page_tipo_idx = 0
        current_page_rows_seen = 0
        current_page_missing_tipo_rows = 0
        page_profile = _page_profile_entry(page_plan, current_page)
        use_standard_page_parser = _should_prefer_standard_page_parser(page_profile, config)
        current_page_use_standard = use_standard_page_parser
        if isinstance(metrics, dict) and use_standard_page_parser:
            metrics["standard_page_fast_path_hits"] = int(metrics.get("standard_page_fast_path_hits") or 0) + 1
        if use_standard_page_parser:
            _metric_block_hit("standard_block_hits", current_page)
            _metric_section_hit("sicro_section_standard_hits", current_page)

        if tipo_candidates is not None and pdf_session is not None and not _session_has_pdfplumber(pdf_session) and not use_standard_page_parser:
            _metric_block_hit("heavy_block_parses", current_page)
            eager_tipo = _should_collect_page_tipo_entries(
                page_profile=page_profile,
                missing_tipo_rows=1,
                rows_seen=1,
                layered_mode=layered_mode,
                tipo_recovery_mode="eager" if tipo_recovery_mode == "eager" and str(page_profile.get("effort") or "") == "heavy" else "on_demand",
            )
            if eager_tipo:
                if isinstance(metrics, dict):
                    metrics["eager_tipo_pages"] = int(metrics.get("eager_tipo_pages") or 0) + 1
                _metric_block_hit("tipo_recovery_block_hits", current_page)
                collected = _collect_tipo_entries_from_pypdf_page(
                    current_page,
                    pdf_session=pdf_session,
                    runtime=runtime,
                    dynamic_markers=dynamic_markers,
                    layout_hint=_block_tipo_layout_hint(current_page),
                    return_layout=True,
                )
                current_page_tipo_entries, learned_layout = collected if isinstance(collected, tuple) else (list(collected or []), {})
                _remember_block_tipo_layout(current_page, learned_layout)
                for entry in current_page_tipo_entries:
                    codigo_candidate = str(entry.get("codigo") or "")
                    banco_candidate = str(entry.get("banco") or "")
                    candidate_tipo = str(entry.get("tipo") or "")
                    if codigo_candidate and banco_candidate and candidate_tipo:
                        _register_tipo_candidate(tipo_candidates, codigo_candidate, banco_candidate, candidate_tipo)

        structured_events = [] if use_standard_page_parser else _extract_structured_text_events_from_page(
            current_page,
            pdf_session=pdf_session,
            runtime=runtime,
            dynamic_markers=dynamic_markers,
            docling_map=docling_map,
        )
        if structured_events:
            if isinstance(metrics, dict):
                metrics["structured_page_parses"] = int(metrics.get("structured_page_parses") or 0) + 1
            _metric_block_hit("heavy_block_parses", current_page)
            _metric_section_hit("sicro_section_template_hits", current_page)
            flush_row()
            structured_has_insumo = False
            for event in structured_events:
                if event.get("event") == "item_header":
                    flush_block()
                    pending_item = _clean(event.get("item", ""))
                    continue
                if event.get("event") != "row":
                    continue
                kind = str(event.get("kind", "") or "")
                cells = list(event.get("cells") or [])
                if not kind or not cells:
                    continue
                if kind == "INSUMO":
                    structured_has_insumo = True
                line, _ = _make_line(
                    cells,
                    dynamic_markers=dynamic_markers,
                    runtime=runtime,
                    finalize_text=finalize_text,
                    kind=kind,
                )
                _register_tipo_candidate(
                    tipo_candidates or {},
                    str(getattr(line, "codigo", "") or ""),
                    str(getattr(line, "banco", "") or ""),
                    str(getattr(line, "tipo", "") or (cells[4] if len(cells) > 4 else "")),
                )
                process_parsed_row(kind, line)
            if structured_has_insumo or "Insumo" not in page_text:
                continue

        skip_sicro_block = False
        for raw_line in page_text.splitlines():
            line = _clean(raw_line)
            if not line:
                continue

            line_norm = _norm(line)
            if skip_sicro_block:
                if (
                    (detect_composition_label(line, config) and "SICRO" not in line_norm and "DNIT" not in line_norm)
                    or (RE_ITEM_HEADER_TEXT.match(line_norm) and "SICRO" not in line_norm and "DNIT" not in line_norm)
                    or (line_has_header_markers(line, runtime["header_cfg"], required_keys=["codigo", "banco"]) and "SICRO" not in line_norm and "DNIT" not in line_norm)
                ):
                    skip_sicro_block = False
                else:
                    if isinstance(metrics, dict):
                        metrics["sicro_section_skip_lines"] = int(metrics.get("sicro_section_skip_lines") or 0) + 1
                    continue
            if _line_starts_sicro_section(line):
                flush_row()
                skip_sicro_block = True
                if isinstance(metrics, dict):
                    metrics["sicro_section_skip_lines"] = int(metrics.get("sicro_section_skip_lines") or 0) + 1
                continue
            head_tokens = line.split()
            if _looks_like_explicit_comp_header_line(line, runtime=runtime):
                flush_block()
                if head_tokens and re.fullmatch(r"\d+(?:\.\d+)*", head_tokens[0]):
                    pending_item = head_tokens[0]
                continue

            m_item = RE_ITEM_HEADER_TEXT.match(line_norm)
            if m_item:
                flush_block()
                pending_item = m_item.group("item")
                continue

            if RE_TABLE_HEADER_TEXT.match(line_norm):
                flush_block()
                continue

            if _looks_like_noise_text_line(line, dynamic_markers=dynamic_markers) or _looks_like_text_section_heading(line):
                continue

            if _norm(line).startswith(("MO SEM", "LS =>", "VALOR DO", "BDI =>")):
                continue

            segments = _split_text_segments(line)
            if not segments:
                continue

            for seg in segments:
                if _looks_like_text_section_heading(seg):
                    continue
                if detect_composition_label(seg, config) or RE_ROW_START_TEXT.match(seg):
                    flush_row()
                    current_row_start = seg
                    current_conts = []
                elif current_row_start:
                    current_conts.append(seg)

    if previous_page_no is not None:
        finalize_page_tipo_recovery(previous_page_no)
    flush_block()
    if isinstance(metrics, dict) and isinstance(block_templates, dict):
        standard_total = sum(1 for block in block_templates.values() if isinstance(block, dict) and str(block.get("template_source") or "") == "standard")
        metrics["standard_block_failures"] = max(0, standard_total - int(metrics.get("standard_block_hits") or 0))
    return blocks



# -------------------------------
# parser principal das composições
# -------------------------------
def parse_composicoes_sinapi(
    pdf_bytes: bytes,
    start_1based: int,
    end_1based: int,
    config: dict,
    item_refs: List[dict],
    context: dict | None = None,
    *,
    pdf_session: PdfDocumentSession | None = None,
):
    avisos: List[str] = []
    erros: List[str] = []
    dynamic_markers = build_dynamic_markers(context or {})
    runtime = _runtime_rules(config)

    orc_by_codebank: Dict[str, dict] = {}
    orc_by_item: Dict[str, dict] = {}
    orc_refs_all: List[dict] = []
    for ref in item_refs or []:
        codigo = _normalize_code_candidate(str(ref.get("codigo", "") or "").strip().upper())
        fonte = _canon_bank(str(ref.get("fonte", "") or "").strip(), runtime=runtime)
        item = str(ref.get("item", "") or "").strip()
        ref_id = str(ref.get("ref_id", "") or "").strip()

        if (not codigo or not fonte) and ref_id and "|" in ref_id:
            codigo_ref, fonte_ref = ref_id.split("|", 1)
            codigo = codigo or _normalize_code_candidate(codigo_ref.strip().upper())
            fonte = fonte or _canon_bank(fonte_ref.strip(), runtime=runtime)

        key = _normalize_ref_key(codigo, fonte)
        normalized_ref = dict(ref)
        if key:
            normalized_ref["codigo"] = codigo
            normalized_ref["fonte"] = fonte
            normalized_ref["ref_id"] = key
            if key not in orc_by_codebank:
                orc_by_codebank[key] = normalized_ref
            if item:
                orc_by_item[item] = normalized_ref
            orc_refs_all.append(normalized_ref)
        elif item:
            orc_by_item[item] = normalized_ref
            orc_refs_all.append(normalized_ref)

    raw_blocks: Dict[str, RawBlock] = {}
    orphan_aux_globals: Dict[str, LinhaComposicao] = {}
    tipo_candidates: Dict[str, str] = {}

    owns_session = pdf_session is None
    session = pdf_session or PdfDocumentSession(pdf_bytes)
    try:
        page_texts_pypdf = session.get_page_texts(start_1based, end_1based, engine="pypdf")
        all_page_numbers = list(range(start_1based, end_1based + 1))
        page_plan = _preclassify_composition_pages(page_texts_pypdf, all_page_numbers, runtime=runtime, config=config)
        candidate_page_numbers = list(page_plan.get("candidate_pages") or all_page_numbers)
        table_candidate_pages = list(page_plan.get("table_candidate_pages") or candidate_page_numbers)
        text_candidate_pages = list(page_plan.get("text_candidate_pages") or candidate_page_numbers)
        sicro_candidate_pages = list(page_plan.get("sicro_candidate_pages") or [])
        pages_with_comp_tables: set[int] = set()
        profile = dict((context or {}).get("document_profile") or {}) if (context or {}).get("header_profile_enabled", True) else {}
        precomputed_tables_by_page: Dict[int, List[List[List[str]]]] = {}
        precomputed_fusion_by_page: Dict[int, Dict[str, Any]] = {}
        for page_no in table_candidate_pages:
            try:
                candidates = build_table_candidates(session, page_no, family="composition", profile=profile)
            except Exception:
                candidates = []
            if not candidates:
                continue
            fused = fuse_table_candidates(candidates)
            best_rows = list(fused.get("best_rows") or [])
            if fused.get("matched") and best_rows:
                precomputed_tables_by_page.setdefault(page_no, []).append(best_rows)
                precomputed_fusion_by_page[page_no] = fused
        if precomputed_tables_by_page:
            table_candidate_pages = sorted(set(table_candidate_pages) | set(precomputed_tables_by_page.keys()))
        table_strategy = _resolve_table_extraction_strategy(config)
        probe_limit = _resolve_table_probe_limit(config)
        final_refinement_only = _final_refinement_only(config)
        compact_debug = _resolve_compact_debug(config)
        table_current: Optional[RawBlock] = None
        table_pending_item = ""

        def _ingest_page_tables(page_no: int) -> None:
            nonlocal table_current, table_pending_item
            page_tables = list(precomputed_tables_by_page.get(page_no) or [])
            extracted_tables = _extract_tables(page_no=page_no, pdf_session=session, runtime=runtime)
            if extracted_tables:
                page_tables.extend(extracted_tables)
            if page_tables:
                pages_with_comp_tables.add(page_no)

            for table in page_tables:
                if not _looks_like_comp_table(table, runtime=runtime):
                    continue

                item_id = _find_table_item_id(table)
                if item_id:
                    if table_current is not None and str(table_current.item or "") and item_id != str(table_current.item or ""):
                        _mark_block_closure(table_current, "novo_item_tabela", page_no=page_no)
                        table_current = None
                    table_pending_item = item_id
                header_mapping, _ = _find_table_header_mapping(table, runtime=runtime)
                start_idx = _find_start_index(table, runtime=runtime)

                for raw in table[start_idx:]:
                    if not raw:
                        continue
                    cells_raw = [_clean(c) for c in raw if c is not None]
                    if not any(cells_raw):
                        continue
                    cells = _canonicalize_table_row(cells_raw, header_mapping)

                    starts_new_table, new_item = _row_starts_new_comp_table(cells, runtime=runtime)
                    if starts_new_table:
                        if table_current is not None:
                            _mark_block_closure(table_current, "cabecalho_novo_item_tabela", page_no=page_no)
                        table_current = None
                        table_pending_item = new_item
                        continue

                    if _looks_like_header(cells, runtime=runtime):
                        continue

                    if _looks_like_cost_footer(cells, runtime=runtime):
                        continue

                    kind = _row_kind_table(cells, runtime=runtime)
                    if not kind:
                        continue

                    line, key = _make_line(cells, dynamic_markers=dynamic_markers, runtime=runtime, finalize_text=not final_refinement_only, kind=kind)
                    _register_tipo_candidate(
                        tipo_candidates,
                        str(getattr(line, "codigo", "") or ""),
                        str(getattr(line, "banco", "") or ""),
                        str(getattr(line, "tipo", "") or (cells[4] if len(cells) > 4 else "")),
                    )
                    if not key and line.banco and table_pending_item:
                        key = _make_recovery_key(table_pending_item, line.banco)
                    if not key:
                        continue

                    starts_new_principal = False
                    if kind == "COMPOSICAO":
                        current_key = ""
                        current_item = ""
                        if table_current is not None and table_current.principal is not None:
                            current_key = _normalize_ref_key(table_current.principal.codigo, table_current.principal.banco)
                            current_item = str(table_current.item or "")

                        if table_current is None or table_current.principal is None:
                            starts_new_principal = True
                        elif table_pending_item:
                            starts_new_principal = True
                        elif key in orc_by_codebank:
                            expected_item = str(orc_by_codebank[key].get("item", "") or "")
                            if expected_item and expected_item != current_item:
                                starts_new_principal = True
                        elif not current_item and key and key != current_key:
                            # v60: without a new header/item, a naked 'Composição' row
                            # can be a continuation or an auxiliary-global fragment. Do
                            # not close the current multipage block purely by code change.
                            starts_new_principal = False

                    if kind == "COMPOSICAO" and starts_new_principal:
                        block_item = table_pending_item if table_pending_item else ""
                        block = raw_blocks.get(key)
                        if block is None:
                            block = RawBlock(item=block_item, key=key, principal=line, page=page_no, page_start=page_no, page_end=page_no, pages_seen=[page_no], detalhes={"origens_extracao": ["table"]})
                            raw_blocks[key] = block
                        else:
                            block.principal = _merge_line(block.principal or line, line)
                            if not block.item and block_item:
                                block.item = block_item
                        _touch_block_page(block, page_no, source="table")
                        if table_current is not None and table_current is not block:
                            _mark_block_closure(table_current, "nova_composicao_tabela", page_no=page_no)
                        if block_item and table_pending_item == block_item:
                            table_pending_item = ""
                        table_current = block
                    elif kind == "COMPOSICAO":
                        if table_current is None:
                            continue
                        table_current.auxiliares.append(line)
                        _touch_block_page(table_current, page_no, source="table")
                    elif kind == "AUXILIAR":
                        if table_current is None:
                            existing = orphan_aux_globals.get(key)
                            orphan_aux_globals[key] = line if existing is None else _merge_line(existing, line)
                            continue
                        table_current.auxiliares.append(line)
                        _touch_block_page(table_current, page_no, source="table")
                    elif kind == "INSUMO":
                        if table_current is None:
                            continue
                        insumo_line = _make_insumo(cells, dynamic_markers=dynamic_markers, finalize_text=not final_refinement_only, runtime=runtime)
                        _register_tipo_candidate(
                            tipo_candidates,
                            str(getattr(insumo_line, "codigo", "") or ""),
                            str(getattr(insumo_line, "banco", "") or ""),
                            str(getattr(insumo_line, "tipo", "") or (cells[4] if len(cells) > 4 else "")),
                        )
                        table_current.insumos.append(insumo_line)
                        _touch_block_page(table_current, page_no, source="table")

        if table_candidate_pages and (precomputed_tables_by_page or _session_has_pdfplumber(session)):
            # A partir da v57.7, a análise estrutural por tabela entra obrigatoriamente no fluxo.
            # Mesmo quando o texto pareça suficiente, o parse precisa comparar a leitura textual
            # com a leitura tabular/fundida para reduzir truncamentos e unidades contaminadas.
            for page_no in table_candidate_pages:
                _ingest_page_tables(page_no)
            if not pages_with_comp_tables:
                avisos.append(
                    f"[composicoes] preclassificacao_paginas: estrategia_tabelas=mandatory; paginas_candidatas={len(candidate_page_numbers)}; paginas_tabela_probed={len(table_candidate_pages)}; tabelas_detectadas=0; fallback_texto_priorizado={len(text_candidate_pages)}"
                )

        if table_candidate_pages and pages_with_comp_tables:
            avisos.append(
                f"[composicoes] preclassificacao_paginas: estrategia_tabelas=mandatory; paginas_candidatas={len(candidate_page_numbers)}; paginas_tabela={len(table_candidate_pages)}; paginas_texto={len(text_candidate_pages)}; tabelas_detectadas={len(pages_with_comp_tables)}; paginas_tabela_precomputadas={len(precomputed_tables_by_page)}"
            )

        if table_current is not None:
            _mark_block_closure(table_current, "fim_intervalo_tabela", page_no=end_1based)

        for block in raw_blocks.values():
            parent_key = _normalize_ref_key(block.principal.codigo, block.principal.banco) if block.principal else ""
            block.auxiliares = _prune_auxiliares_against_insumos(block.auxiliares, block.insumos, parent_key=parent_key or block.key)
            block.insumos = [LinhaInsumo(**x.model_dump()) for x in _dedup_lines(block.insumos)]

        text_fallback_mode = _resolve_text_fallback_mode(config)
        text_source_pages = text_candidate_pages or candidate_page_numbers or all_page_numbers
        selected_text_pages = _select_text_fallback_pages(text_source_pages, pages_with_comp_tables, mode=text_fallback_mode, pages_with_open_block=set())
        pure_sicro_pages = set(page_plan.get("pure_sicro_pages") or [])
        dedicated_sicro_pages = set(page_plan.get("dedicated_sicro_pages") or [])
        include_pure_sicro_generic = _resolve_generic_text_include_pure_sicro_pages(config)
        skipped_generic_sicro_pages: List[int] = []
        skip_generic_sicro_pages = dedicated_sicro_pages or pure_sicro_pages
        if skip_generic_sicro_pages and not include_pure_sicro_generic:
            filtered = [page_no for page_no in selected_text_pages if page_no not in skip_generic_sicro_pages]
            if filtered:
                skipped_generic_sicro_pages = [page_no for page_no in selected_text_pages if page_no in skip_generic_sicro_pages]
                selected_text_pages = filtered
        selected_texts = [page_texts_pypdf[page_no - start_1based] for page_no in selected_text_pages if start_1based <= page_no <= end_1based]
        text_blocks = _extract_blocks_from_text(
            pdf_bytes=pdf_bytes,
            start_1based=start_1based,
            end_1based=end_1based,
            context=context,
            config=config,
            page_texts=selected_texts,
            page_numbers=selected_text_pages,
            pdf_session=session,
            finalize_text=not final_refinement_only,
            tipo_candidates=tipo_candidates,
            page_plan=page_plan,
        )
        fallback_msg = f"[composicoes] fallback_texto={text_fallback_mode}; paginas_texto={len(selected_text_pages)}; paginas_tabela={len(pages_with_comp_tables)}; paginas_sicro={len(sicro_candidate_pages)}; refinamento_final={str(final_refinement_only).lower()}; validacao_tabelas=mandatory; precomputadas={len(precomputed_tables_by_page)}"
        if compact_debug and _is_fast_profile(config):
            block_count = len(page_plan.get("blocks") or []) if isinstance(page_plan, dict) else 0
            metrics = dict((page_plan or {}).get("metrics") or {}) if isinstance(page_plan, dict) else {}
            fallback_msg = f"[composicoes] fallback_texto={text_fallback_mode}; paginas_texto={len(selected_text_pages)}; paginas_tabela={len(pages_with_comp_tables)}; paginas_sicro={len(sicro_candidate_pages)}; blocos={block_count}; modo_intervalo={_resolve_interval_processing_mode(config)}"
            if skipped_generic_sicro_pages:
                fallback_msg += f"; sicro_dedicado={len(skipped_generic_sicro_pages)}"
            if metrics:
                fallback_msg += (
                    f"; modelo_padrao_paginas={int(metrics.get('standard_model_pages') or 0)}"
                    f"; fast_path={int(metrics.get('standard_page_fast_path_hits') or 0)}"
                    f"; standard_blocks={int(metrics.get('standard_block_hits') or 0)}"
                    f"; heavy_blocks={int(metrics.get('heavy_block_parses') or 0)}"
                    f"; estruturado={int(metrics.get('structured_page_parses') or 0)}"
                    f"; tipo_eager={int(metrics.get('eager_tipo_pages') or 0)}"
                    f"; tipo_ondemand={int(metrics.get('on_demand_tipo_pages') or 0)}"
                    f"; tipo_blocos={int(metrics.get('tipo_recovery_block_hits') or 0)}"
                    f"; blocos_sicro={int(metrics.get('sicro_block_count') or 0)}"
                    f"; sicro_doc_lock={int(metrics.get('sicro_doc_profile_locked') or 0)}"
                )
        avisos.append(fallback_msg)
        sicro_page_numbers = sorted(set((sicro_candidate_pages or []) + list(page_plan.get("dedicated_sicro_pages") or []))) or all_page_numbers
        sicro_page_texts = [page_texts_pypdf[page_no - start_1based] for page_no in sicro_page_numbers if start_1based <= page_no <= end_1based]
        raw_blocks = _merge_sicro_blocks(
            raw_blocks,
            extract_sicro_blocks_from_text(
                pdf_bytes=pdf_bytes,
                start_1based=start_1based,
                end_1based=end_1based,
                item_refs=item_refs,
                page_texts=sicro_page_texts,
                page_numbers=sicro_page_numbers,
                section_templates={sec: dict(meta) for block in (page_plan.get("blocks") or []) for sec, meta in ((block.get("sicro_templates") or {}).items())} if isinstance(page_plan, dict) else None,
                page_section_hints={page_no: list((_page_profile_entry(page_plan, page_no).get("sicro_sections") or [])) for page_no in sicro_page_numbers} if isinstance(page_plan, dict) else None,
            ),
        )
        for key, text_block in text_blocks.items():
            norm_key = key
            if not _is_recovery_key(norm_key) and "|" in norm_key:
                code, bank = norm_key.split("|", 1)
                norm_key = _normalize_ref_key(code, bank)
                text_block.key = norm_key
            if norm_key not in raw_blocks:
                raw_blocks[norm_key] = text_block
                continue
            base = raw_blocks[norm_key]
            if base.principal is not None and _canon_bank(base.principal.banco, runtime=runtime) == "SICRO":
                if not base.item and text_block.item:
                    base.item = text_block.item
                continue
            chosen = _choose_best_block_variant(base, text_block)
            raw_blocks[norm_key] = chosen

        normalized_blocks: Dict[str, RawBlock] = {}
        for key, block in raw_blocks.items():
            target_key = key
            if _is_recovery_key(key) and block.item:
                item_ref = orc_by_item.get(block.item)
                if item_ref is not None:
                    expected_key = str(item_ref.get("ref_id", "") or "").strip()
                    if expected_key:
                        target_key = expected_key
                        codigo_ref = _normalize_code_candidate(str(item_ref.get("codigo", "") or "").strip().upper())
                        fonte_ref = _canon_bank(str(item_ref.get("fonte", "") or "").strip())
                        if block.principal is not None:
                            block.principal.codigo = block.principal.codigo or codigo_ref
                            block.principal.banco = block.principal.banco or fonte_ref
                            block.principal.banco_coluna = block.principal.banco_coluna or fonte_ref
            elif "|" in key:
                codigo_key, banco_key = key.split("|", 1)
                target_key = _normalize_ref_key(codigo_key, banco_key)

            existing = normalized_blocks.get(target_key)
            if existing is None:
                block.key = target_key
                normalized_blocks[target_key] = block
            else:
                if not existing.item and block.item:
                    existing.item = block.item
                if existing.principal is None and block.principal is not None:
                    existing.principal = block.principal
                elif existing.principal is not None and block.principal is not None:
                    existing.principal = _merge_line(existing.principal, block.principal)
                parent_key = _normalize_ref_key(existing.principal.codigo, existing.principal.banco) if existing.principal else target_key
                existing.auxiliares = _prune_auxiliares_against_insumos(list(existing.auxiliares) + list(block.auxiliares), list(existing.insumos) + list(block.insumos), parent_key=parent_key)
                existing.insumos = [LinhaInsumo(**x.model_dump()) for x in _dedup_lines(list(existing.insumos) + list(block.insumos))]

        for block in normalized_blocks.values():
            if block.principal is not None:
                block.principal.codigo = _normalize_code_candidate(block.principal.codigo)
                block.principal.banco = _canon_bank(block.principal.banco)
                block.principal.banco_coluna = _canon_bank(block.principal.banco_coluna or block.principal.banco)
                block.principal.descricao = _sanitize_description(block.principal.descricao, code=block.principal.codigo, bank=block.principal.banco, dynamic_markers=dynamic_markers)
                _touch_block_page(block, block.page or start_1based, source='normalized')
            parent_key = _normalize_ref_key(block.principal.codigo, block.principal.banco) if block.principal else block.key
            block.auxiliares = _prune_auxiliares_against_insumos(block.auxiliares, block.insumos, parent_key=parent_key)
            for line in block.auxiliares:
                line.codigo = _normalize_code_candidate(line.codigo)
                line.banco = _canon_bank(line.banco or (block.principal.banco if block.principal else ''))
                line.banco_coluna = _canon_bank(line.banco_coluna or line.banco)
                if not line.und and block.principal is not None and _canon_bank(line.banco) == _canon_bank(block.principal.banco):
                    line.und = line.und or ''
                line.descricao = _sanitize_description(line.descricao, code=line.codigo, bank=line.banco, dynamic_markers=dynamic_markers)
            for line in block.insumos:
                line.codigo = _normalize_code_candidate(line.codigo)
                line.banco = _canon_bank(line.banco or (block.principal.banco if block.principal else ''))
                line.banco_coluna = _canon_bank(line.banco_coluna or line.banco)
                line.descricao = _sanitize_description(line.descricao, code=line.codigo, bank=line.banco, dynamic_markers=dynamic_markers)
                if line.total is None and line.quant is not None and line.valor_unit is not None:
                    line.total = round(float(line.quant) * float(line.valor_unit), 6)
                    _note_block_recovery(block, f"total_insumo_recalculado:{line.codigo}|{line.banco}")
            detalhes = dict(block.detalhes or {})
            detalhes['pagina_inicio'] = block.page_start or detalhes.get('pagina_inicio')
            detalhes['pagina_fim'] = block.page_end or detalhes.get('pagina_fim')
            detalhes['paginas'] = list(block.pages_seen or detalhes.get('paginas') or [])
            missing_rows = []
            principal_line = block.principal
            if principal_line is not None:
                for field in ('codigo','banco','descricao','und','quant','valor_unit','total'):
                    if getattr(principal_line, field, None) in ('', None):
                        missing_rows.append(f'principal:{field}')
            for line in list(block.auxiliares or []) + list(block.insumos or []):
                for field in ('codigo','banco','descricao','und','quant'):
                    if getattr(line, field, None) in ('', None):
                        missing_rows.append(f"{getattr(line, 'codigo', '') or 'linha'}:{field}")
            if missing_rows:
                detalhes['status_completude'] = 'pendente_revisao'
                detalhes['campos_faltantes_detectados'] = missing_rows[:40]
                _note_block_recovery(block, 'diagnostico_campos_vazios')
            else:
                detalhes['status_completude'] = detalhes.get('status_completude') or 'completo'
            block.detalhes = detalhes

        block_aliases = _build_block_truncation_aliases(normalized_blocks, orc_by_codebank)
        if block_aliases:
            merged_blocks: Dict[str, RawBlock] = {}
            for key, block in normalized_blocks.items():
                target_key = block_aliases.get(key, key)
                if target_key != key and block.principal is not None and "|" in target_key:
                    target_code, target_bank = target_key.split("|", 1)
                    block.principal.codigo = target_code
                    block.principal.banco = target_bank
                    block.principal.banco_coluna = target_bank
                target = merged_blocks.get(target_key)
                if target is None:
                    block.key = target_key
                    merged_blocks[target_key] = block
                else:
                    merged_blocks[target_key] = _merge_raw_blocks(target, block)
            normalized_blocks = merged_blocks

        for block in normalized_blocks.values():
            parent_key = _normalize_ref_key(block.principal.codigo, block.principal.banco) if block.principal else block.key
            rewritten_aux: List[LinhaComposicao] = []
            for line in block.auxiliares:
                line = _rewrite_aux_line_to_known_block(line, normalized_blocks, block_aliases)
                rewritten_aux.append(line)
            block.auxiliares = _prune_auxiliares_against_insumos(rewritten_aux, block.insumos, parent_key=parent_key)

        _backfill_missing_tipos_in_blocks(normalized_blocks, orphan_aux_globals, tipo_candidates)

        catalog_principals: Dict[str, RawBlock] = normalized_blocks
        referenced_aux_keys = {
            _normalize_ref_key(a.codigo, a.banco)
            for b in catalog_principals.values()
            for a in b.auxiliares
            if a.codigo and a.banco
        }
        referenced_aux_keys.discard("")
        catalog_principals = _materialize_missing_referenced_blocks(catalog_principals, referenced_aux_keys, orphan_aux_globals)

        principais: Dict[str, BlocoComposicao] = {}
        auxiliares_globais: Dict[str, BlocoComposicao] = {}
        orphan_aux_keys = set()

        for key in orphan_aux_globals:
            norm_key = key
            if not _is_recovery_key(norm_key) and "|" in norm_key:
                code, bank = norm_key.split("|", 1)
                norm_key = _normalize_ref_key(code, bank)
            if norm_key:
                orphan_aux_keys.add(norm_key)

        for key, block in catalog_principals.items():
            if _is_structural_noise_block(block):
                avisos.append(f"[composicoes] bloco estrutural ignorado no anexo: {key} ({getattr(block.principal, 'descricao', '')}).")
                continue

            ref = orc_by_codebank.get(key)
            if ref is None and block.item:
                item_ref = orc_by_item.get(block.item)
                if item_ref is not None and str(item_ref.get("ref_id", "") or "") == key:
                    ref = item_ref

            is_aux_catalog = key in referenced_aux_keys or key in orphan_aux_keys
            if block.principal is None:
                continue

            if ref is not None:
                block.item = str(ref.get("item", "") or block.item or "")
                aux_out, ins_out, detalhes_out = _output_block_parts(block)
                bloco = BlocoComposicao(
                    item=block.item,
                    principal=block.principal,
                    composicoes_auxiliares=aux_out,
                    insumos=ins_out,
                    detalhes=detalhes_out,
                )
                codigo_orc = _normalize_code_candidate(str(ref.get("codigo", "") or ""))
                codigo_comp = _normalize_code_candidate(str(block.principal.codigo or ""))
                _append_orcamento_relation(
                    bloco,
                    {
                        "status": "associada_diretamente",
                        "criterio": "codigo_banco",
                        "item_orcamento": block.item,
                        "ref_id_orcamento": str(ref.get("ref_id", "") or key),
                        "codigo_orcamento": codigo_orc,
                        "codigo_composicao_encontrado": codigo_comp,
                        "chave_bloco": key,
                        "divergencia_codigo": bool(codigo_orc and codigo_comp and codigo_orc != codigo_comp),
                        "suspeitas": _relation_suspeitas("associada_diretamente", codigo_orc, codigo_comp),
                    },
                )
                principais[key] = bloco
                continue

            if is_aux_catalog:
                aux_out, ins_out, detalhes_out = _output_block_parts(block)
                auxiliares_globais[key] = BlocoComposicao(
                    item="",
                    principal=block.principal,
                    composicoes_auxiliares=aux_out,
                    insumos=ins_out,
                    detalhes=detalhes_out,
                )
                continue

            aux_out, ins_out, detalhes_out = _output_block_parts(block)
            bloco = BlocoComposicao(
                item=block.item or "",
                principal=block.principal,
                composicoes_auxiliares=aux_out,
                insumos=ins_out,
                detalhes=detalhes_out,
            )
            codigo_comp = _normalize_code_candidate(str(block.principal.codigo or ""))
            _append_orcamento_relation(
                bloco,
                {
                    "status": "nao_associada_diretamente_no_orcamento",
                    "criterio": "bloco_principal_sem_item_correspondente",
                    "item_orcamento": str(block.item or ""),
                    "ref_id_orcamento": "",
                    "codigo_orcamento": "",
                    "codigo_composicao_encontrado": codigo_comp,
                    "chave_bloco": key,
                    "suspeitas": _relation_suspeitas("nao_associada_diretamente_no_orcamento", "", codigo_comp),
                },
            )
            principais[key] = bloco

        for key, line in orphan_aux_globals.items():
            norm_key = key
            if not _is_recovery_key(norm_key) and "|" in norm_key:
                code, bank = norm_key.split("|", 1)
                norm_key = _normalize_ref_key(code, bank)
            if not norm_key or norm_key in auxiliares_globais:
                continue
            line.codigo = _normalize_code_candidate(line.codigo)
            line.banco = _canon_bank(line.banco)
            line.banco_coluna = _canon_bank(line.banco_coluna or line.banco)
            line.descricao = _sanitize_description(line.descricao, code=line.codigo, bank=line.banco, dynamic_markers=dynamic_markers)
            auxiliares_globais[norm_key] = BlocoComposicao(
                item="",
                principal=line,
                composicoes_auxiliares=[],
                insumos=[],
            )

        aliases_aux: Dict[str, str] = dict(block_aliases)
        all_known_keys = set(auxiliares_globais) | set(principais)
        for ref_key in sorted(referenced_aux_keys):
            if ref_key in all_known_keys or "|" not in ref_key:
                continue
            codigo, banco = ref_key.split("|", 1)
            digits = re.sub(r"[^0-9]", "", codigo)
            if len(digits) <= 5:
                continue
            for n in range(len(digits) - 1, 4, -1):
                cand = digits[:n]
                cand_key = _normalize_ref_key(cand, banco)
                if cand_key in all_known_keys:
                    aliases_aux[ref_key] = cand_key
                    break

        principais, dispensados_refs, vinculados_flex = _apply_flexible_ref_resolution(
            orc_refs_all=orc_refs_all,
            principais=principais,
            auxiliares_globais=auxiliares_globais,
            avisos=avisos,
            config=config,
        )

        _clear_spurious_items_from_unassociated_blocks(principais)

        itens_faltando = _compute_missing_refs(orc_refs_all, principais, dispensados_refs, config=config)
        composicoes_nao_associadas = sorted(
            key
            for key, bloco in principais.items()
            if not any(
                str(rel.get("status") or "").strip() in _ASSOCIATED_RELATION_STATUSES
                for rel in _iter_orcamento_relations(bloco)
            )
        )
        associacoes_por_indicio = []
        for key, bloco in principais.items():
            for rel in _iter_orcamento_relations(bloco):
                if str(rel.get("status") or "").strip() != "associada_por_indicio":
                    continue
                assoc = dict(rel)
                assoc.setdefault("chave_bloco", key)
                associacoes_por_indicio.append(assoc)

        aux_counts = sorted(len(bloco.composicoes_auxiliares) for bloco in principais.values())
        if aux_counts:
            mediana_aux = aux_counts[len(aux_counts) // 2]
            limite_aux = max(25, mediana_aux * 8 if mediana_aux else 25)
            suspeitos = [
                (key, len(bloco.composicoes_auxiliares))
                for key, bloco in principais.items()
                if len(bloco.composicoes_auxiliares) > limite_aux
            ]
            if suspeitos:
                exemplos = ", ".join(f"{key}={qtd}" for key, qtd in sorted(suspeitos, key=lambda x: x[1], reverse=True)[:10])
                avisos.append(
                    f"[composicoes] anomalia estrutural: {len(suspeitos)} composição(ões) com excesso de auxiliares diretos. "
                    f"Mediana={mediana_aux}; limite={limite_aux}. Exemplos: {exemplos}"
                )

        comp = Composicoes(
            principais=principais,
            auxiliares_globais=auxiliares_globais,
            aliases_auxiliares=aliases_aux,
        )

        avisos.append(
            f"[composicoes] páginas {start_1based}-{end_1based}; blocos_brutos={len(catalog_principals)}; "
            f"principais={len(principais)}; auxiliares_globais={len(auxiliares_globais)}; aliases={len(aliases_aux)}"
        )
        if composicoes_nao_associadas:
            exemplos = ", ".join(composicoes_nao_associadas[:10])
            avisos.append(
                f"[composicoes] {len(composicoes_nao_associadas)} composição(ões) não associada(s) diretamente no orçamento. Exemplos: {exemplos}"
            )
        if associacoes_por_indicio:
            exemplos = ", ".join(
                f"{assoc.get('item_orcamento', '')}->{assoc.get('chave_bloco', '')}" for assoc in associacoes_por_indicio[:10]
            )
            avisos.append(
                f"[composicoes] {len(associacoes_por_indicio)} composição(ões) associada(s) por indício ao orçamento. Exemplos: {exemplos}"
            )

        return comp, avisos, erros, itens_faltando, composicoes_nao_associadas, associacoes_por_indicio
    finally:
        if owns_session:
            session.close()



def _strip_all_relations_from_comp(comp: Composicoes) -> Composicoes:
    for catalog in (comp.principais or {}, comp.auxiliares_globais or {}):
        for block in catalog.values():
            detalhes = dict(getattr(block, "detalhes", {}) or {})
            detalhes.pop("relacao_orcamento", None)
            detalhes.pop("relacoes_orcamento", None)
            detalhes.pop("vinculo_flexivel", None)
            block.detalhes = detalhes
    return comp


def reapply_orcamento_relations(
    comp: Composicoes,
    item_refs: list[dict] | None,
    config: dict | None = None,
) -> tuple[Composicoes, list[str], list[str], list[str], list[dict]]:
    """Reaplica relações orçamento↔composição após uma extração independente do orçamento.

    Usado principalmente pelo modo browser paralelo, onde orçamento e composições são extraídos em tarefas separadas.
    """
    avisos: list[str] = []
    runtime = _runtime_rules(config)
    comp = _strip_all_relations_from_comp(comp)

    principais: Dict[str, BlocoComposicao] = {k: _clone_bloco(v) for k, v in (comp.principais or {}).items()}
    auxiliares_globais: Dict[str, BlocoComposicao] = {k: _clone_bloco(v) for k, v in (comp.auxiliares_globais or {}).items()}

    orc_by_codebank: Dict[str, dict] = {}
    orc_by_item: Dict[str, dict] = {}
    orc_refs_all: List[dict] = []
    for ref in item_refs or []:
        codigo = _normalize_code_candidate(str(ref.get("codigo", "") or "").strip().upper())
        fonte = _canon_bank(str(ref.get("fonte", "") or "").strip(), runtime=runtime)
        item = str(ref.get("item", "") or "").strip()
        ref_id = str(ref.get("ref_id", "") or "").strip()
        if (not codigo or not fonte) and ref_id and "|" in ref_id:
            codigo_ref, fonte_ref = ref_id.split("|", 1)
            codigo = codigo or _normalize_code_candidate(codigo_ref.strip().upper())
            fonte = fonte or _canon_bank(fonte_ref.strip(), runtime=runtime)
        key = _normalize_ref_key(codigo, fonte)
        normalized_ref = dict(ref)
        if key:
            normalized_ref["codigo"] = codigo
            normalized_ref["fonte"] = fonte
            normalized_ref["ref_id"] = key
            orc_by_codebank.setdefault(key, normalized_ref)
            if item:
                orc_by_item[item] = normalized_ref
            orc_refs_all.append(normalized_ref)
        elif item:
            orc_by_item[item] = normalized_ref
            orc_refs_all.append(normalized_ref)

    # promove auxiliares globais quando o código do orçamento os referencia diretamente
    for ref_key, ref in list(orc_by_codebank.items()):
        if ref_key in principais:
            bloco = principais[ref_key]
        elif ref_key in auxiliares_globais:
            bloco = auxiliares_globais.pop(ref_key)
            principais[ref_key] = bloco
        else:
            continue
        bloco.item = str(ref.get("item", "") or bloco.item or "")
        codigo_orc = _normalize_code_candidate(str(ref.get("codigo", "") or ""))
        codigo_comp = _normalize_code_candidate(str(bloco.principal.codigo or ""))
        _append_orcamento_relation(
            bloco,
            {
                "status": "associada_diretamente",
                "criterio": "codigo_banco",
                "item_orcamento": bloco.item,
                "ref_id_orcamento": str(ref.get("ref_id", "") or ref_key),
                "codigo_orcamento": codigo_orc,
                "codigo_composicao_encontrado": codigo_comp,
                "chave_bloco": ref_key,
                "divergencia_codigo": bool(codigo_orc and codigo_comp and codigo_orc != codigo_comp),
                "suspeitas": _relation_suspeitas("associada_diretamente", codigo_orc, codigo_comp),
            },
        )

    principais, dispensados_refs, _ = _apply_flexible_ref_resolution(
        orc_refs_all=orc_refs_all,
        principais=principais,
        auxiliares_globais=auxiliares_globais,
        avisos=avisos,
        config=config,
    )

    _clear_spurious_items_from_unassociated_blocks(principais)

    itens_faltando = _compute_missing_refs(orc_refs_all, principais, dispensados_refs, config=config)
    composicoes_nao_associadas = sorted(
        key
        for key, bloco in principais.items()
        if not any(
            str(rel.get("status") or "").strip() in _ASSOCIATED_RELATION_STATUSES
            for rel in _iter_orcamento_relations(bloco)
        )
    )
    associacoes_por_indicio: list[dict] = []
    for key, bloco in principais.items():
        for rel in _iter_orcamento_relations(bloco):
            if str(rel.get("status") or "").strip() != "associada_por_indicio":
                continue
            assoc = dict(rel)
            assoc.setdefault("chave_bloco", key)
            associacoes_por_indicio.append(assoc)

    return (
        Composicoes(principais=principais, auxiliares_globais=auxiliares_globais, aliases_auxiliares=dict(comp.aliases_auxiliares or {})),
        avisos,
        itens_faltando,
        composicoes_nao_associadas,
        associacoes_por_indicio,
    )


# Compatibilidade interna
parse_compositions_document = parse_composicoes_sinapi
