from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .sicro_engine import SicroEngine, clean, parse_decimal


def _bbox_from_evidence(ev: Dict[str, Any]) -> Optional[List[float]]:
    if not ev:
        return None
    if ev.get("bbox_first_page"):
        return [float(x) for x in ev["bbox_first_page"]]
    if ev.get("bbox"):
        return [float(x) for x in ev["bbox"]]
    lines = ev.get("lines") or []
    bboxes = [ln.get("bbox") for ln in lines if ln.get("bbox")]
    if not bboxes:
        return None
    return [min(b[0] for b in bboxes), min(b[1] for b in bboxes), max(b[2] for b in bboxes), max(b[3] for b in bboxes)]


def _all_words(ev: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if ev.get("words"):
        out.extend(ev.get("words") or [])
    for ln in ev.get("lines") or []:
        out.extend(ln.get("words") or [])
    return out


def _median_span(spans: Iterable[Tuple[float, float]], page_width: float = 595.0) -> Dict[str, Any]:
    vals = [(float(a), float(b)) for a, b in spans if b >= a]
    if not vals:
        return {"x0": None, "x1": None, "observations": 0, "confidence": 0.0}
    x0s = [a for a, _ in vals]
    x1s = [b for _, b in vals]
    spread = (max(x1s) - min(x0s)) if vals else 999.0
    conf = max(0.1, min(0.99, 1.0 - (spread / 700.0)))
    return {"x0": round(median(x0s), 2), "x1": round(median(x1s), 2), "x0_norm": round(median(x0s) / page_width, 4) if page_width else None, "x1_norm": round(median(x1s) / page_width, 4) if page_width else None, "observations": len(vals), "confidence": round(conf, 3)}


@dataclass
class ProfileObservation:
    section: str
    field: str
    x0: float
    x1: float
    source: str
    weight: float = 1.0
    composition: str = ""


@dataclass
class SicroDocumentProfile:
    """Learned layout profile for a SICRO document.

    This profile is collected during the first pass and consolidated before the
    second pass. It is intentionally JSON-serializable and Pyodide-friendly.
    """

    engine: SicroEngine = field(default_factory=SicroEngine)
    observations: List[ProfileObservation] = field(default_factory=list)
    section_rows: Dict[str, List[List[float]]] = field(default_factory=lambda: {s: [] for s in "ABCDEF"})
    section_headers: Dict[str, List[List[float]]] = field(default_factory=lambda: {s: [] for s in "ABCDEF"})
    banks_seen: Dict[str, int] = field(default_factory=dict)
    composition_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_results(results: Iterable[Dict[str, Any]], engine: SicroEngine | None = None) -> "SicroDocumentProfile":
        profile = SicroDocumentProfile(engine=engine or SicroEngine())
        for result in results:
            if result:
                profile.observe_result(result)
        profile.metadata["source_result_count"] = len([r for r in results if r]) if not isinstance(results, list) else len([r for r in results if r])
        return profile

    def observe_result(self, result: Dict[str, Any]) -> None:
        for comp_key, comp in (result.get("composicoes") or {}).items():
            self.composition_count += 1
            bank = (comp.get("principal") or {}).get("banco")
            if bank:
                self.banks_seen[bank] = self.banks_seen.get(bank, 0) + 1
            for sec, section in (comp.get("secoes") or {}).items():
                header_bbox = _bbox_from_evidence(section.get("header_evidence") or {})
                if header_bbox:
                    self.section_headers.setdefault(sec, []).append(header_bbox)
                for row in section.get("linhas") or []:
                    ev = row.get("_evidence") or {}
                    bbox = _bbox_from_evidence(ev)
                    if bbox:
                        self.section_rows.setdefault(sec, []).append(bbox)
                    weight = 1.0
                    if (row.get("validacao") or {}).get("ok"):
                        weight += 1.0
                    if row.get("_recovery"):
                        weight -= 0.25
                    self._observe_fields_from_words(comp_key, sec, row, ev, weight)

    def _observe_fields_from_words(self, comp_key: str, sec: str, row: Dict[str, Any], ev: Dict[str, Any], weight: float) -> None:
        # Preferred v61.0.15 path: field-level bboxes are produced during row
        # assembly, so we do not need to keep every word in the public result.
        fev = row.get("_field_evidence") or {}
        if fev:
            for field_name, field_ev in fev.items():
                bbox = field_ev.get("bbox")
                if not bbox:
                    continue
                self.observations.append(ProfileObservation(
                    section=sec,
                    field=field_name,
                    x0=float(bbox[0]),
                    x1=float(bbox[2]),
                    source="field_evidence",
                    weight=max(0.1, weight),
                    composition=comp_key,
                ))
            return
        # Backward-compatible fallback for old v61.0.14 outputs.
        words = _all_words(ev)
        if not words:
            return
        fields = ["codigo", "insumo", "banco", "unidade", "quantidade", "preco_unitario", "custo_horario", "salario_hora"]
        for field_name in fields:
            val = clean(row.get(field_name))
            if not val:
                continue
            val_key = val.replace(" ", "").upper()
            matches = [w for w in words if clean(w.get("text")).replace(" ", "").upper() == val_key]
            if not matches and field_name == "banco":
                matches = [w for w in words if clean(w.get("text")).upper().startswith("SICRO")]
            if matches:
                chosen = sorted(matches, key=lambda w: float(w.get("x0", 0.0)))[-1]
                self.observations.append(ProfileObservation(sec, field_name, float(chosen["x0"]), float(chosen["x1"]), "field_word_match", max(0.1, weight), comp_key))

    def consolidated(self) -> Dict[str, Any]:
        sections: Dict[str, Any] = {}
        for sec in "ABCDEF":
            field_bands: Dict[str, Any] = {}
            fields = sorted({o.field for o in self.observations if o.section == sec})
            for field in fields:
                spans: List[Tuple[float, float]] = []
                for o in self.observations:
                    if o.section != sec or o.field != field:
                        continue
                    # Weight by duplicating. Small integer duplication is enough and deterministic.
                    times = max(1, min(4, int(round(o.weight))))
                    spans.extend([(o.x0, o.x1)] * times)
                field_bands[field] = _median_span(spans)
            sections[sec] = {
                "row_span": _median_span((b[0], b[2]) for b in self.section_rows.get(sec, [])),
                "header_span": _median_span((b[0], b[2]) for b in self.section_headers.get(sec, [])),
                "field_bands": field_bands,
                "row_observations": len(self.section_rows.get(sec, [])),
                "header_observations": len(self.section_headers.get(sec, [])),
            }
        return {
            "version": "v61.0.20-sicro-learned-layout-profile",
            "composition_count_observed": self.composition_count,
            "banks_seen": self.banks_seen,
            "sections": sections,
            "layout_clusters": self._layout_clusters(sections),
            "observation_count": len(self.observations),
            "metadata": self.metadata,
        }

    def _layout_clusters(self, sections: Dict[str, Any]) -> Dict[str, Any]:
        """Lightweight profile clusters by section completeness.

        A document may have normal pages, short auxiliary compositions, and
        transport-heavy pages. The cluster data prevents one family from
        contaminating another when future second-pass extraction chooses a local
        layout.
        """
        clusters: Dict[str, Any] = {}
        for sec, data in sections.items():
            obs = int(data.get("row_observations") or 0)
            fields = sorted((data.get("field_bands") or {}).keys())
            if not obs:
                continue
            if sec == "F":
                name = "transport_section"
            elif obs <= 2:
                name = "short_auxiliary_section"
            else:
                name = "standard_section"
            clusters.setdefault(name, {"sections": {}, "total_row_observations": 0})
            clusters[name]["sections"][sec] = {"row_observations": obs, "fields": fields}
            clusters[name]["total_row_observations"] += obs
        return clusters

    def field_band(self, section: str, field: str) -> Dict[str, Any]:
        return self.consolidated().get("sections", {}).get(section, {}).get("field_bands", {}).get(field, {})


def profile_confirms_field(profile_data: Dict[str, Any], section: str, field: str, ev: Dict[str, Any]) -> bool:
    band = profile_data.get("sections", {}).get(section, {}).get("field_bands", {}).get(field, {})
    if not band or band.get("x0") is None or band.get("x1") is None:
        return False
    bbox = _bbox_from_evidence(ev)
    if not bbox:
        return False
    cx = (bbox[0] + bbox[2]) / 2.0
    # Field-level bbox may not be available; line-level center is weak evidence.
    # Accept if the row overlaps the learned section span or if center is in band.
    return float(band["x0"]) - 40 <= cx <= float(band["x1"]) + 40
