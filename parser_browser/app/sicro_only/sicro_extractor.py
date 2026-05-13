from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sicro_engine import SicroEngine, clean, key
from .sicro_geometry import Line, extract_pymupdf_lines, extract_pymupdf_text_lines, union_bbox

SECTION_BY_HEADER_PREFIX = {
    "A": ("A CODIGO BANCO EQUIP", "A CÓDIGO BANCO EQUIP"),
    "B": ("B CODIGO BANCO MAO DE OBRA", "B CÓDIGO BANCO MÃO DE OBRA", "B CODIGO BANCO MÃO DE OBRA"),
    "C": ("C BANCO CODIGO MATERIAL", "C BANCO CÓDIGO MATERIAL"),
    "D": ("D BANCO CODIGO ATIVIDADES AUX", "D BANCO CÓDIGO ATIVIDADES AUX"),
    "E": ("E BANCO INSUMO TEMPOS FIXOS",),
    "F": ("F BANCO INSUMO MOMENTO DE TRANSPORTE",),
}

SUMMARY_STARTS = (
    "CUSTO HORARIO", "CUSTO HORÁRIO", "CUSTO TOTAL", "ADC.M.O", "FATOR DE INFLUENCIA", "FATOR DE INFLUÊNCIA",
    "CUSTO DO FIC", "PRODUCAO DE EQUIPE", "PRODUÇÃO DE EQUIPE", "CUSTO UNITARIO", "CUSTO UNITÁRIO",
    "PRECO UNITARIO", "PREÇO UNITÁRIO", "MO SEM LS", "VALOR DO BDI", "VALOR COM BDI",
)

ROW_STARTS = {
    "A": (r"^(?:Insumo\s+)?E\s*\d{3,5}\s+SICRO",),
    "B": (r"^(?:Insumo\s+)?P\s*\d{3,5}\s+SICRO",),
    "C": (r"^Insumo\s+SICRO\s*(?:2|3)?\s+M\s*\d{3,5}\b",),
    "D": (r"^(?:Atividade\s+Auxiliar|Composi(?:ç[aã]o|cao)\s+Auxiliar|Auxiliar)\s+SICRO",),
    "E": (r"^Tempo\s+Fixo\s+SICRO",),
    "F": (r"^Momento\s+de\b", r"^Momento\s+de\s+Transporte\b", r"^SICRO\s*(?:2|3)?\s+M\s*\d{3,5}\b"),
}


@dataclass
class CompositionBlock:
    key: str
    principal: Dict[str, Any]
    pages: List[int] = field(default_factory=list)
    sections: Dict[str, List[Dict[str, Any]]] = field(default_factory=lambda: {k: [] for k in "ABCDEF"})
    row_validations: List[Dict[str, Any]] = field(default_factory=list)
    summaries: Dict[str, str] = field(default_factory=dict)
    raw_trace: List[Dict[str, Any]] = field(default_factory=list)
    section_headers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def add_page(self, page: int) -> None:
        if page not in self.pages:
            self.pages.append(page)
            self.pages.sort()


def _field_word_evidence(row: Dict[str, Any], lines: List[Line]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    all_words = []
    for ln in lines:
        for w in ln.words:
            all_words.append({"x0": float(w[0]), "y0": float(w[1]), "x1": float(w[2]), "y1": float(w[3]), "text": str(w[4]), "page": ln.page, "source": ln.source})
    if not all_words:
        return out
    fields = ["codigo", "insumo", "banco", "unidade", "quantidade", "preco_unitario", "custo_horario", "salario_hora"]
    description_fields = ["servico", "equipamento", "mao_obra", "material", "atividade_auxiliar", "tempo_fixo", "momento_transporte"]
    used = set()
    for field in fields:
        val = clean(row.get(field))
        if not val:
            continue
        val_key = val.replace(" ", "").upper()
        matches = []
        for idx, w in enumerate(all_words):
            w_key = clean(w["text"]).replace(" ", "").upper()
            if w_key == val_key:
                matches.append((idx, w))
        if not matches and field == "banco":
            matches = [(idx, w) for idx, w in enumerate(all_words) if clean(w["text"]).upper().startswith("SICRO")]
        if matches:
            # For repeated numeric tokens, rightmost unused match usually maps to the active table column.
            matches = sorted(matches, key=lambda item: (item[1]["page"], item[1]["x0"]))
            chosen_idx, chosen = next(((idx, w) for idx, w in reversed(matches) if idx not in used), matches[-1])
            used.add(chosen_idx)
            out[field] = {
                "page": chosen["page"],
                "bbox": [round(chosen["x0"], 2), round(chosen["y0"], 2), round(chosen["x1"], 2), round(chosen["y1"], 2)],
                "source": chosen["source"],
                "text": chosen["text"],
                "strategy": "exact_word_match",
            }

    # Description cells are usually wrapped and cannot be matched as one word.
    # Match a robust subset of words and union their bbox; this feeds the learned
    # description band so future wrapped fragments can be reattached upstream.
    for field in description_fields:
        val = clean(row.get(field))
        if not val:
            continue
        wanted = [clean(x).upper().strip('.,;:-') for x in val.split() if len(clean(x).strip('.,;:-')) > 2]
        if not wanted:
            continue
        selected = []
        wanted_set = set(wanted)
        for idx, w in enumerate(all_words):
            wk = clean(w["text"]).upper().strip('.,;:-')
            if wk in wanted_set:
                selected.append((idx, w))
        if len(selected) >= max(1, min(3, len(wanted) // 3)):
            bxs = [w for _, w in selected]
            out[field] = {
                "page": bxs[0]["page"],
                "bbox": [round(min(w["x0"] for w in bxs), 2), round(min(w["y0"] for w in bxs), 2), round(max(w["x1"] for w in bxs), 2), round(max(w["y1"] for w in bxs), 2)],
                "source": bxs[0]["source"],
                "text": " ".join(w["text"] for w in bxs[:12]),
                "strategy": "description_word_union",
            }
    return out


class SicroGeometryExtractor:
    """SICRO-only extractor for laboratory tests.

    v61.0.13 deliberately refuses silent downgrade from PyMuPDF geometry to pypdf
    when mode is "auto" or "pymupdf". SICRO tables depend on x/y word geometry.
    A text-only fallback can still be implemented as an explicit diagnostic outside
    this class, but it must not masquerade as production extraction.
    """

    VERSION = "v61.0.20-sicro-audit-confidence-boundary"

    def __init__(self, engine: Optional[SicroEngine] = None, keep_raw_trace: bool = True, line_tolerance: float | None = None, profile_name: str = "adaptive"):
        self.engine = engine or SicroEngine()
        self.keep_raw_trace = keep_raw_trace
        self.mode = "pymupdf_words"
        self.line_tolerance = line_tolerance
        self.profile_name = profile_name

    def _page_lines_pymupdf(self, pdf_path: str | Path, start_page: int, end_page: int) -> List[Line]:
        return extract_pymupdf_lines(pdf_path, start_page, end_page, tolerance=self.line_tolerance)

    def page_lines(self, pdf_path: str | Path, start_page: int, end_page: int, mode: str = "auto") -> List[Line]:
        if mode not in {"auto", "pymupdf", "pymupdf_words", "pymupdf_text_diagnostic"}:
            raise ValueError(f"Modo SICRO inválido para v61.0.14: {mode}. Use pymupdf_words.")
        if mode == "pymupdf_text_diagnostic":
            self.mode = "pymupdf_text_diagnostic"
            return extract_pymupdf_text_lines(pdf_path, start_page, end_page)
        self.mode = "pymupdf_words"
        return self._page_lines_pymupdf(pdf_path, start_page, end_page)

    def _detect_section(self, text: str) -> str:
        k = key(text)
        for section, prefixes in SECTION_BY_HEADER_PREFIX.items():
            if any(k.startswith(key(p)) for p in prefixes):
                return section
        return ""

    def _is_summary_or_noise(self, text: str) -> bool:
        k = key(text)
        if any(k.startswith(s) for s in SUMMARY_STARTS):
            return True
        if k in {"HORARIO", "HORÁRIO", "OPERATIVA IMPRODUTIVA", "OPERATIV A", "IMPRODU TIVA", "LN RP P", "TIPO"}:
            return True
        return False

    def _is_any_section_header(self, text: str) -> bool:
        return bool(self._detect_section(text))

    def _is_principal_start(self, text: str) -> bool:
        return bool(re.match(r"^Composi(?:ç[aã]o|cao)\s+\d{7}\s+SICRO\s*(?:2|3)?\b", clean(text), flags=re.I))

    def _is_any_composition_start(self, text: str) -> bool:
        return bool(re.match(r"^Composi(?:ç[aã]o|cao)\b", clean(text), flags=re.I))

    def _looks_like_description_continuation(self, line: Line, previous: Line | None = None) -> bool:
        text = clean(line.text)
        if not text:
            return False
        if self._is_any_section_header(text) or self._is_any_composition_start(text) or self._starts_new_row_any_section(text):
            return False
        if self._is_summary_or_noise(text) or self.engine.parse_summary(text) or self.engine.is_footer_or_header_noise(text):
            return False
        # Continuation fragments are textual, but valid SICRO descriptions often
        # contain dimensions/weights such as 3,40 m³ or 15 t. Reject only fragments
        # that are mostly numeric.
        nums = self.engine.numbers(text)
        alpha_count = len(re.findall(r"[A-Za-zÀ-ÿ]", text))
        if nums and alpha_count < 3:
            return False
        if len(text.split()) > 14:
            return False
        if any(k in key(text) for k in ("CODIGO", "BANCO", "QUANT", "VALOR", "CUSTO", "TOTAL", "DERACRE", "PAGINA")):
            return False
        # If we have geometry, prefer fragments beginning inside the normal
        # description band. This catches wrapped descriptions while rejecting
        # right-side numeric/table artifacts.
        if previous is not None:
            same_page = line.page == previous.page
            cross_page_cont = line.page == previous.page + 1 and previous.y > 700 and line.y < 140
            if not (same_page or cross_page_cont):
                return False
        x0 = line.bbox[0] if line.bbox else 0
        return 120 <= x0 <= 260 or (previous is not None and line.page == previous.page and abs(line.y - previous.y) < 16)

    def _is_row_start(self, section: str, text: str) -> bool:
        for pat in ROW_STARTS.get(section, ()):  # pragma: no branch - small tuple
            if re.match(pat, clean(text), flags=re.I):
                return True
        return False

    def _starts_new_row_any_section(self, text: str) -> bool:
        return any(self._is_row_start(sec, text) for sec in "ABCDEF")

    def _collect_principal(self, lines: List[Line], i: int) -> Tuple[str, int, List[Line]]:
        parts = [lines[i].text]
        evidence = [lines[i]]
        consumed = 1
        j = i + 1
        while j < len(lines) and consumed < 8:
            candidate = clean(" ".join(parts))
            parsed_ok = self.engine.parse_principal(candidate) is not None
            if parsed_ok:
                # Even when the principal already parses, SICRO descriptions often
                # wrap after the numeric tail. Collect text-only continuation lines
                # and let the engine move them before the tail.
                if j < len(lines) and self._looks_like_description_continuation(lines[j], evidence[-1]):
                    parts.append(lines[j].text)
                    evidence.append(lines[j])
                    consumed += 1
                    j += 1
                    continue
                break
            if j >= len(lines):
                break
            nxt = lines[j].text
            if self._is_any_section_header(nxt) or self._starts_new_row_any_section(nxt) or self._is_any_composition_start(nxt):
                break
            if self.engine.is_footer_or_header_noise(nxt) or self.engine.parse_summary(nxt):
                break
            # While principal is not parseable yet, allow normal multiline service
            # text. This handles long first rows and page-boundary wrapping.
            if not (lines[j].page == lines[i].page or (lines[j].page == evidence[-1].page + 1 and evidence[-1].y > 700 and lines[j].y < 140)):
                break
            parts.append(nxt)
            evidence.append(lines[j])
            consumed += 1
            j += 1
        return clean(" ".join(parts)), consumed, evidence

    def _collect_row(self, lines: List[Line], i: int, section: str) -> Tuple[str, int, List[Line]]:
        parts = [lines[i].text]
        evidence = [lines[i]]
        consumed = 1
        j = i + 1
        while j < len(lines) and lines[j].page == lines[i].page:
            nxt = lines[j].text
            if self._is_any_section_header(nxt) or self._is_principal_start(nxt):
                break
            if self._is_any_composition_start(nxt) and not self._is_row_start(section, nxt):
                break
            if self._is_summary_or_noise(nxt) and section != "F":
                break
            if self._starts_new_row_any_section(nxt) and not (section == "F" and not self._is_row_start("F", nxt)):
                break
            parts.append(nxt)
            evidence.append(lines[j])
            consumed += 1
            j += 1
            if consumed > (10 if section == "F" else 6):
                break
        return clean(" ".join(parts)), consumed, evidence

    def _append_trace(self, block: CompositionBlock, line: Line, event: str, text: str) -> None:
        if not self.keep_raw_trace:
            return
        ev = line.evidence()
        ev.update({"event": event, "text": text})
        block.raw_trace.append(ev)

    def extract(self, pdf_path: str | Path, start_page: int, end_page: int, mode: str = "auto", item_refs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        t0 = time.perf_counter()
        lines = self.page_lines(pdf_path, start_page, end_page, mode=mode)
        refs_by_code = {str(r.get("codigo") or r.get("code") or "").strip(): r for r in (item_refs or [])}
        blocks: Dict[str, CompositionBlock] = {}
        current: Optional[CompositionBlock] = None
        current_section = ""
        i = 0
        while i < len(lines):
            line = lines[i]
            text = line.text
            section = self._detect_section(text)
            if section and current:
                current_section = section
                current.add_page(line.page)
                current.section_headers[section] = line.evidence()
                self._append_trace(current, line, f"section_{section}_header", text)
                i += 1
                continue

            if self._is_principal_start(text):
                principal_text, consumed, evidence = self._collect_principal(lines, i)
                principal = self.engine.parse_principal(principal_text)
                if principal:
                    ref = refs_by_code.get(principal["codigo"], {})
                    principal["item"] = str(ref.get("item") or "")
                    principal["_evidence"] = union_bbox(evidence)
                    principal["_field_evidence"] = _field_word_evidence(principal, evidence)
                    block_key = f"{principal['codigo']}|{principal['banco']}"
                    current = blocks.get(block_key)
                    if current is None:
                        current = CompositionBlock(key=block_key, principal=principal)
                        blocks[block_key] = current
                    else:
                        current.principal = principal
                    for ev_line in evidence:
                        current.add_page(ev_line.page)
                    current_section = ""
                    self._append_trace(current, line, "principal", principal_text)
                    i += consumed
                    continue

            if self._is_any_composition_start(text) and not self._is_principal_start(text) and current and not (current_section and self._is_row_start(current_section, text)):
                current = None
                current_section = ""
                i += 1
                continue

            if current is None:
                i += 1
                continue

            summary = self.engine.parse_summary(text)
            if summary:
                current.summaries.update(summary)
                current.add_page(line.page)
                self._append_trace(current, line, "summary", text)
                i += 1
                continue

            if current_section and self._is_row_start(current_section, text):
                row_text, consumed, evidence = self._collect_row(lines, i, current_section)
                parsed = self.engine.parse_section_row(current_section, row_text)
                if parsed is None and consumed > 1:
                    row_text = text
                    consumed = 1
                    evidence = [line]
                    parsed = self.engine.parse_section_row(current_section, row_text)
                if parsed is not None:
                    row = dict(parsed.row)
                    row["validacao"] = parsed.validation.as_dict()
                    row["_evidence"] = union_bbox(evidence)
                    row["_field_evidence"] = _field_word_evidence(row, evidence)
                    current.sections[current_section].append(row)
                    current.row_validations.append({"section": current_section, "codigo": row.get("codigo") or row.get("insumo"), **parsed.validation.as_dict()})
                    for ev_line in evidence:
                        current.add_page(ev_line.page)
                    self._append_trace(current, line, f"row_{current_section}", row_text)
                    i += consumed
                    continue

            i += 1

        result_blocks: Dict[str, Any] = {block_key: self._materialize_block(block) for block_key, block in blocks.items()}
        issues: List[Dict[str, Any]] = []
        for key_, block in result_blocks.items():
            for issue in block.get("validacao", {}).get("issues", []):
                issues.append({"composicao": key_, **issue})
        return {
            "metadata": {
                "version": self.VERSION,
                "mode": self.mode,
                "pdf": str(pdf_path),
                "page_range": [start_page, end_page],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "total_composicoes": len(result_blocks),
                "total_issues": len(issues),
                "geometry_required": True,
                "text_fallback_allowed": False,
                "profile": self.profile_name,
                "line_tolerance": self.line_tolerance,
            },
            "composicoes": result_blocks,
            "issues": issues,
        }

    def _materialize_block(self, block: CompositionBlock) -> Dict[str, Any]:
        public_sections: Dict[str, Any] = {}
        lettered_sections: Dict[str, Any] = {}
        issues: List[Dict[str, Any]] = []
        for sec in "ABCDEF":
            rows = block.sections.get(sec, [])
            public_key = self.engine.sections.get(sec, {}).get("public_key", sec)
            reported_key = {
                "A": "custo_horario_equipamentos",
                "B": "custo_horario_mao_obra",
                "C": "custo_total_material",
                "D": "custo_total_atividades_auxiliares",
                "E": "custo_total_tempos_fixos",
                "F": "custo_total_momentos_transporte",
            }[sec]
            section_validation = self.engine.validate_section_total(rows, block.summaries.get(reported_key)).as_dict()
            if not section_validation.get("ok", True):
                issues.append({"tipo": "section_total", "section": sec, "public_key": public_key, **section_validation})
            for row in rows:
                val = row.get("validacao", {})
                if val and not val.get("ok", True):
                    issues.append({"tipo": "row_math", "section": sec, "public_key": public_key, "codigo": row.get("codigo") or row.get("insumo"), **val})
            if rows:
                public_sections[public_key] = rows
                lettered_sections[sec] = {
                    "nome": self.engine.sections.get(sec, {}).get("name", sec),
                    "public_key": public_key,
                    "header_evidence": block.section_headers.get(sec, {}),
                    "linhas": rows,
                    "total_reportado": block.summaries.get(reported_key),
                    "validacao_total": section_validation,
                }
        principal_val = block.principal.get("validacao", {})
        if principal_val and not principal_val.get("ok", True):
            issues.append({"tipo": "principal_math", **principal_val})
        summary_validation = self.engine.validate_composition_summary(block.principal, block.summaries)
        for issue in summary_validation.get("issues", []):
            issues.append({"tipo": "summary_math", **issue})
        return {
            "principal": {k: v for k, v in block.principal.items() if k not in {"raw_text"}},
            "paginas": block.pages,
            "secoes": lettered_sections,
            "sicro": public_sections,
            "resumos": block.summaries,
            "validacao": {
                "ok": not issues,
                "issues": issues,
                "row_validations": block.row_validations,
                "summary_validation": summary_validation,
            },
            "raw_trace": block.raw_trace,
        }
