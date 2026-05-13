from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .sicro_audit import audit_extraction_contract
from .sicro_engine import SicroEngine
from .sicro_fusion import SicroEvidenceFusionEngine
from .sicro_multiengine import EngineProfile, DEFAULT_PROFILES, SicroMultiEngineExtractor
from .sicro_profile import SicroDocumentProfile
from .sicro_quality import annotate_confidence, score_extraction_result
from .sicro_text_integrity import repair_text_integrity
from .sicro_document_consistency import validate_document_consistency
from .sicro_words_cache import words_cache_report, clear_global_words_cache


class SicroTwoPassPipeline:
    """Profiled SICRO pipeline with optional stabilization pass.

    Pass 1: run all engines, collect evidence, learn the document layout profile.
    Pass 2: re-run engines, consolidate the global profile and fuse fields.
    Pass 3: only runs when the second-pass result still has issues or when
    ``force_passes`` asks for it. This keeps Pyodide/browser runtime safe while
    still allowing aggressive laboratory testing.
    """

    VERSION = "v61.0.20-browser-audit-confidence-boundary"

    def __init__(
        self,
        engine: SicroEngine | None = None,
        profiles: Optional[List[EngineProfile]] = None,
        keep_raw_trace: bool = True,
        max_passes: int = 3,
        force_passes: int | None = None,
    ):
        self.engine = engine or SicroEngine()
        self.profiles = profiles or DEFAULT_PROFILES
        self.keep_raw_trace = keep_raw_trace
        self.max_passes = max(2, min(3, self._coerce_optional_int(max_passes, default=3) or 3))
        fp = self._coerce_optional_int(force_passes, default=None)
        self.force_passes = None if fp is None else max(2, min(3, fp))

    @staticmethod
    def _coerce_optional_int(value: Any, default: int | None = None) -> int | None:
        """Coerce browser/Pyodide values safely.

        Pyodide converts JavaScript null into a JsNull proxy. ``int(JsNull)``
        raises TypeError, so browser controls that mean "auto" must be treated
        like Python None. This helper is intentionally permissive because the
        same adapter is used by CPython tests, Pyodide and Lovable.
        """
        if value is None:
            return default
        text = str(value).strip()
        if text in {"", "None", "none", "null", "undefined", "JsNull"}:
            return default
        if text.lower() in {"nan", "auto"}:
            return default
        try:
            return int(float(text))
        except Exception:
            return default

    def _run_candidates(self, pdf_path: str | Path, start_page: int, end_page: int, item_refs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        runner = SicroMultiEngineExtractor(self.engine, self.profiles, self.keep_raw_trace)
        return runner.run_candidates(pdf_path, start_page, end_page, item_refs=item_refs)

    def _learn_profile(self, candidates_by_pass: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        obj = SicroDocumentProfile(engine=self.engine)
        for candidates in candidates_by_pass:
            for cand in candidates:
                result = cand.get("result")
                if result:
                    obj.observe_result(result)
        return obj.consolidated()

    def _select(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        production = [c for c in candidates if c.get("result") is not None and c.get("profile", {}).get("production")]
        pool = production or [c for c in candidates if c.get("result") is not None]
        if not pool:
            return {"metadata": {"total_composicoes": 0, "total_issues": 0}, "composicoes": {}, "issues": []}
        winner = max(pool, key=lambda c: c.get("score", {}).get("score", -999999))
        result = winner.get("result")
        result.setdefault("metadata", {})["selected_profile"] = winner.get("profile", {}).get("name")
        result["metadata"]["selected_score"] = winner.get("score")
        result["multiengine"] = {
            "winner": winner.get("profile", {}).get("name"),
            "candidates": [{"profile": c.get("profile"), "score": c.get("score")} for c in candidates],
            "selection_rule": "production winner used as base; field-level fusion can replace weak fields",
        }
        return result

    def _fuse_and_audit(self, selected: Dict[str, Any], candidates: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
        fused = SicroEvidenceFusionEngine(self.engine, profile).fuse(selected, candidates)
        contract = audit_extraction_contract(fused)
        fused["contract_audit"] = {"ok": not contract, "issues": contract}
        fused.setdefault("metadata", {})["total_contract_issues"] = len(contract)
        fused["metadata"]["total_issues"] = len(fused.get("issues") or [])
        return fused

    def _needs_stabilization(self, fused: Dict[str, Any]) -> bool:
        if self.force_passes and self.force_passes >= 3:
            return True
        if self.max_passes < 3:
            return False
        return bool(fused.get("issues")) or bool((fused.get("contract_audit") or {}).get("issues"))

    def extract(self, pdf_path: str | Path, start_page: int, end_page: int, item_refs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        # Start each public full extraction with a clean cache. The cache is then
        # reused across profiles and passes inside this run, avoiding stale pages
        # from earlier tests/Lovable calls while preserving performance.
        clear_global_words_cache()
        pass_candidates: List[List[Dict[str, Any]]] = []

        first = self._run_candidates(pdf_path, start_page, end_page, item_refs=item_refs)
        pass_candidates.append(first)
        first_profile = self._learn_profile(pass_candidates)

        second = self._run_candidates(pdf_path, start_page, end_page, item_refs=item_refs)
        pass_candidates.append(second)
        second_profile = self._learn_profile(pass_candidates)
        selected = self._select(second)
        fused = self._fuse_and_audit(selected, second, second_profile)
        actual_passes = 2

        third_profile = None
        third = None
        if self._needs_stabilization(fused):
            third = self._run_candidates(pdf_path, start_page, end_page, item_refs=item_refs)
            pass_candidates.append(third)
            third_profile = self._learn_profile(pass_candidates)
            third_selected = self._select(third)
            third_fused = self._fuse_and_audit(third_selected, third, third_profile)
            # Keep the third pass only if it does not make the result worse.
            old_score = (score_extraction_result(fused).get("score") or 0)
            new_score = (score_extraction_result(third_fused).get("score") or 0)
            if new_score >= old_score or self.force_passes:
                fused = third_fused
                actual_passes = 3
            else:
                actual_passes = 2

        final_profile = third_profile or second_profile
        fused = repair_text_integrity(fused)
        fused = validate_document_consistency(fused, pdf_path)
        fused = annotate_confidence(fused, self.engine)
        fused.setdefault("metadata", {})["pipeline_version"] = self.VERSION
        fused["metadata"]["two_pass_enabled"] = True
        fused["metadata"]["stabilization_pass_available"] = self.max_passes >= 3
        fused["metadata"]["actual_passes"] = actual_passes
        fused["metadata"]["first_pass_profile_observations"] = first_profile.get("observation_count", 0)
        fused["metadata"]["final_profile_observations"] = final_profile.get("observation_count", 0)
        fused["metadata"]["words_cache"] = words_cache_report()
        first_pass_report = {"index": 1, "candidate_count": len(first), "profile": first_profile, "candidates": [{"profile": c.get("profile"), "score": c.get("score")} for c in first]}
        second_pass_report = {"index": 2, "candidate_count": len(second), "profile": second_profile, "candidates": [{"profile": c.get("profile"), "score": c.get("score")} for c in second]}
        fused["two_pass"] = {
            "version": self.VERSION,
            "first_pass": first_pass_report,
            "second_pass": second_pass_report,
            "passes": [first_pass_report, second_pass_report],
            "final_profile": final_profile,
            "guarantee": "all final compositions are parsed again after the learned profile is consolidated; a third stabilization pass runs if required",
        }
        if third is not None:
            third_pass_report = {"index": 3, "candidate_count": len(third), "profile": third_profile, "used_as_final": actual_passes == 3, "candidates": [{"profile": c.get("profile"), "score": c.get("score")} for c in third]}
            fused["two_pass"]["passes"].append(third_pass_report)
            fused["two_pass"]["third_pass"] = third_pass_report
        return fused
