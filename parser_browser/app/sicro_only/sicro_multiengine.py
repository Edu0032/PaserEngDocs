from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sicro_audit import audit_extraction_contract
from .sicro_engine import SicroEngine
from .sicro_extractor import SicroGeometryExtractor
from .sicro_fusion import SicroEvidenceFusionEngine
from .sicro_profile import SicroDocumentProfile
from .sicro_quality import annotate_confidence, score_extraction_result
from .sicro_words_cache import clear_global_words_cache


@dataclass(frozen=True)
class EngineProfile:
    name: str
    mode: str = "pymupdf_words"
    line_tolerance: float | None = None
    production: bool = True


DEFAULT_PROFILES: List[EngineProfile] = [
    EngineProfile("words_adaptive", "pymupdf_words", None, True),
    EngineProfile("words_tight_2_0", "pymupdf_words", 2.0, True),
    EngineProfile("words_loose_3_2", "pymupdf_words", 3.2, True),
    EngineProfile("text_diagnostic", "pymupdf_text_diagnostic", None, False),
]


class SicroMultiEngineExtractor:
    """Run several PyMuPDF-based SICRO engines, then fuse field candidates.

    v61.0.20 keeps whole-engine scoring for diagnostics, but the returned result is
    assembled by the Evidence Fusion layer whenever safe. Text mode remains
    diagnostic-only and cannot be the production source.
    """

    VERSION = "v61.0.20-sicro-multiengine-field-fusion"

    def __init__(self, engine: Optional[SicroEngine] = None, profiles: Optional[List[EngineProfile]] = None, keep_raw_trace: bool = True, enable_fusion: bool = True):
        self.engine = engine or SicroEngine()
        self.profiles = profiles or DEFAULT_PROFILES
        self.keep_raw_trace = keep_raw_trace
        self.enable_fusion = enable_fusion

    def run_candidates(self, pdf_path: str | Path, start_page: int, end_page: int, item_refs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        page_count = max(0, int(end_page) - int(start_page) + 1)
        for profile in self.profiles:
            # Full-document browser runs should not spend time on diagnostic text
            # fallback. It cannot win production selection and can be very slow on
            # long PDFs in Pyodide. Keep it for small lab ranges where it is useful
            # for divergence reports.
            if not profile.production and page_count > 50:
                candidates.append({
                    "profile": profile.__dict__,
                    "score": {"score": -999998, "skipped": True, "reason": "diagnostic profile skipped for large page range", "profile": profile.name, "production": profile.production},
                    "result": None,
                })
                continue
            try:
                extractor = SicroGeometryExtractor(
                    self.engine,
                    keep_raw_trace=self.keep_raw_trace,
                    line_tolerance=profile.line_tolerance,
                    profile_name=profile.name,
                )
                result = extractor.extract(pdf_path, start_page, end_page, mode=profile.mode, item_refs=item_refs)
                result = annotate_confidence(result, self.engine)
                contract = audit_extraction_contract(result)
                result["contract_audit"] = {"ok": not contract, "issues": contract}
                score = score_extraction_result(result, contract)
                score["production"] = profile.production
                score["profile"] = profile.name
                candidates.append({"profile": profile.__dict__, "score": score, "result": result})
            except Exception as exc:  # pragma: no cover - exercised by integration failures
                candidates.append({"profile": profile.__dict__, "score": {"score": -999999, "error": repr(exc), "profile": profile.name, "production": profile.production}, "result": None})
        return candidates

    def _select_winner(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        production_candidates = [c for c in candidates if c["result"] is not None and c["profile"].get("production")]
        if not production_candidates:
            winner = max(candidates, key=lambda c: c.get("score", {}).get("score", -999999)) if candidates else {"profile": {}, "score": {}, "result": None}
        else:
            winner = max(production_candidates, key=lambda c: c.get("score", {}).get("score", -999999))
        selected = winner.get("result") or {"metadata": {}, "composicoes": {}, "issues": []}
        selected.setdefault("metadata", {})["selected_profile"] = winner.get("profile", {}).get("name")
        selected["metadata"]["selected_score"] = winner.get("score")
        selected["multiengine"] = {
            "winner": winner.get("profile", {}).get("name"),
            "candidates": [
                {"profile": c["profile"], "score": c["score"], "metadata": (c.get("result") or {}).get("metadata", {})}
                for c in candidates
            ],
            "selection_rule": "highest production score; text mode is diagnostic-only; field fusion may override weak fields",
        }
        return selected

    def extract(self, pdf_path: str | Path, start_page: int, end_page: int, item_refs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        # Public one-shot calls should not inherit cached pages from previous
        # unrelated test/probe runs. Two-pass orchestration calls run_candidates
        # directly and still benefits from cross-pass cache reuse.
        clear_global_words_cache()
        candidates = self.run_candidates(pdf_path, start_page, end_page, item_refs=item_refs)
        selected = self._select_winner(candidates)
        if self.enable_fusion:
            profile_obj = SicroDocumentProfile(engine=self.engine)
            for c in candidates:
                if c.get("result"):
                    profile_obj.observe_result(c["result"])
            profile = profile_obj.consolidated()
            selected = SicroEvidenceFusionEngine(self.engine, profile).fuse(selected, candidates)
        contract = audit_extraction_contract(selected)
        selected["contract_audit"] = {"ok": not contract, "issues": contract}
        selected.setdefault("metadata", {})["multiengine_version"] = self.VERSION
        selected["metadata"]["fusion_enabled"] = self.enable_fusion
        selected["metadata"]["total_contract_issues"] = len(contract)
        if "multiengine" not in selected:
            selected["multiengine"] = {"candidates": []}
        return selected
