from __future__ import annotations
import copy, json, re
from typing import Any, Dict, List, Tuple
from app.config.version import CURRENT_RELEASE
from app.core.correction_report import build_correction_document
from app.parser.correction_decision_report import augment_correction_with_repair_summary
from app.core.output_compact import prune_runtime_only_fields
from app.parser.broken_line_recovery import pollution_reason, similarity
from app.parser.field_patch_validators import candidate_kind, normalize_field_name, validate_patch_candidate

def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

def _norm(value: Any) -> str:
    text = _clean_text(value).upper()
    repl = str.maketrans({"Á":"A","À":"A","Â":"A","Ã":"A","É":"E","Ê":"E","Í":"I","Ó":"O","Ô":"O","Õ":"O","Ú":"U","Ç":"C"})
    return text.translate(repl)

def _get_path(root: Any, path: List[Any]) -> Tuple[bool, Any]:
    cur = root
    for part in path:
        try:
            if isinstance(cur, list): cur = cur[int(part)]
            elif isinstance(cur, dict): cur = cur[part]
            else: return False, None
        except Exception: return False, None
    return True, cur

def _set_path(root: Any, path: List[Any], value: Any) -> Tuple[bool, Any, Any]:
    if not path: return False, None, None
    ok, parent = _get_path(root, path[:-1])
    if not ok: return False, None, None
    key = path[-1]
    try:
        if isinstance(parent, list):
            idx = int(key); before = parent[idx]; parent[idx] = value
        elif isinstance(parent, dict):
            before = parent.get(key); parent[key] = value
        else: return False, None, None
    except Exception: return False, None, None
    return True, before, value

def _field_is_description_patch(patch: Dict[str, Any]) -> bool:
    return str(patch.get("field") or "").strip() in {"descricao", "especificacao"}

def _value_is_valid_description(value: Any) -> bool:
    text = _clean_text(value)
    if len(text) < 3: return False
    if re.fullmatch(r"[\d\s.,%/\-]+", text): return False
    if _norm(text) in {"SINAPI","SICRO","SICRO3","PROPRIO","PRÓPRIO","H","UN","M","M2","M3"}: return False
    if pollution_reason(text): return False
    return True

def _contains_token_sequence(container: Any, part: Any) -> bool:
    c = _norm(container).split(); p = _norm(part).split()
    if not c or not p or len(p) > len(c): return False
    for i in range(0, len(c) - len(p) + 1):
        if c[i:i + len(p)] == p: return True
    return False

def _current_allows_patch(current: Any, value: Any, issue: str = "", evidence: Dict[str, Any] | None = None) -> bool:
    cur = _clean_text(current); val = _clean_text(value)
    if not cur: return True
    if similarity(cur, val) >= 0.97:
        return False
    issue_l = str(issue or "").lower()
    strategy = str((evidence or {}).get("candidate_strategy") or "")
    starts = _norm(val).startswith(_norm(cur))
    contains = _contains_token_sequence(val, cur)
    # Never accept a hypothesis that makes an already coherent current value less
    # similar. This enforces "first, do no harm" for budget/SINAPI patches.
    if strategy == "upward_target_downward_fragments" and cur and not ("trunc" in issue_l or _norm(cur).split()[-1:] in [["COM"],["DE"],["DA"],["DO"],["PARA"],["EM"]]):
        return False
    if "trunc" in issue_l:
        return len(val) > len(cur) and (starts or contains) and similarity(cur, val) >= 0.70
    if "broken" in issue_l or strategy in {"upward_fragments_plus_target", "target_plus_downward_fragments", "confirmed_description_registry"}:
        return len(val) > len(cur) + 3 and (starts or contains) and similarity(cur, val) >= 0.72
    return len(val) > len(cur) + 8 and starts

def _current_allows_generic_patch(field: str, current: Any, value: Any, issue: str = "", evidence: Dict[str, Any] | None = None) -> bool:
    kind = candidate_kind(field)
    if kind == "description":
        return _current_allows_patch(current, value, issue, evidence)
    cur = _clean_text(current)
    val = _clean_text(value)
    if not val:
        return False
    if not cur:
        return True
    if _norm(cur) == _norm(val):
        return False
    issue_l = str(issue or "").lower()
    # Only replace non-textual values when the target was explicitly marked as
    # empty/suspect by closure/deep sweep.  This prevents overwriting coherent
    # extracted values with a coincidental numeric token.
    if any(token in issue_l for token in ["missing", "empty", "unclosed", "suspect", "math"]):
        return True
    return False


def _row_identity_matches(row: Any, patch: Dict[str, Any]) -> bool:
    if not isinstance(row, dict): return False
    codigo = _clean_text(patch.get("codigo")); banco = _clean_text(patch.get("banco"))
    if codigo and _norm(row.get("codigo")) != _norm(codigo): return False
    if banco:
        row_bank = _clean_text(row.get("banco") or row.get("fonte") or row.get("banco_coluna"))
        if row_bank and _norm(row_bank) != _norm(banco): return False
    return True

def _candidate_rows_by_identity(final_result: Dict[str, Any], patch: Dict[str, Any]) -> List[Tuple[List[Any], Dict[str, Any]]]:
    comp = final_result.get("composicoes") or {}; candidates=[]
    collections = [str(patch.get("collection") or "").strip()] if patch.get("collection") else ["principais","auxiliares_globais"]
    row_groups = [str(patch.get("row_group") or "").strip()] if patch.get("row_group") else ["principal","composicoes_auxiliares","insumos","materiais","mao_obra","equipamentos","auxiliares","detalhes"]
    comp_key = str(patch.get("comp_key") or patch.get("key") or "").strip()

    def iter_blocks(collection: str):
        if isinstance(comp.get(collection), dict):
            yield ["composicoes", collection], comp.get(collection) or {}
        for family in ("sinapi_like", "sicro"):
            fam = comp.get(family) if isinstance(comp.get(family), dict) else {}
            blocks = fam.get(collection) if isinstance(fam, dict) else None
            if isinstance(blocks, dict):
                yield ["composicoes", family, collection], blocks

    for collection in [c for c in collections if c]:
        for base_path, blocks in iter_blocks(collection):
            block_items = [(comp_key, blocks[comp_key])] if comp_key and comp_key in blocks else list(blocks.items())
            for key, block in block_items:
                if not isinstance(block, dict): continue
                if "principal" in row_groups and isinstance(block.get("principal"), dict) and _row_identity_matches(block.get("principal"), patch):
                    candidates.append((base_path + [key, "principal"], block["principal"]))
                for group in row_groups:
                    if group == "principal": continue
                    rows = block.get(group)
                    if not isinstance(rows, list): continue
                    for idx, row in enumerate(rows):
                        if isinstance(row, dict) and _row_identity_matches(row, patch):
                            candidates.append((base_path + [key, group, idx], row))
    return candidates

def _resolve_patch_target(final_result: Dict[str, Any], patch: Dict[str, Any]) -> Tuple[bool, List[Any], Dict[str, Any] | None, str]:
    raw_path = list(patch.get("path") or []); field = str(patch.get("field") or "descricao")
    row_path = raw_path[:-1] if raw_path and raw_path[-1] == field else raw_path
    ok, row = _get_path(final_result, row_path)
    if ok and isinstance(row, dict) and _row_identity_matches(row, patch): return True, row_path, row, "path"
    # Budget targets do not live under composicoes. Prefer the explicit path,
    # then fall back to walking the synthetic budget tree by codigo/fonte.
    if str(patch.get("family") or patch.get("table_family") or "").lower() in {"budget", "orcamento", "orcamento_sintetico"}:
        candidates: List[Tuple[List[Any], Dict[str, Any]]] = []
        def walk(nodes: Any, base_path: List[Any]) -> None:
            if not isinstance(nodes, list):
                return
            for idx, node in enumerate(nodes):
                if not isinstance(node, dict):
                    continue
                path = base_path + [idx]
                if _row_identity_matches(node, patch):
                    candidates.append((path, node))
                walk(node.get("filhos"), path + ["filhos"])
        walk(((final_result.get("orcamento_sintetico") or {}).get("itens_raiz") or []), ["orcamento_sintetico", "itens_raiz"])
        if len(candidates) == 1:
            return True, candidates[0][0], candidates[0][1], "budget_identity_unique"
        if len(candidates) > 1:
            item_hint = str(patch.get("item") or "").strip()
            filtered = [(p, r) for p, r in candidates if not item_hint or str(r.get("item") or "").strip() == item_hint]
            if len(filtered) == 1:
                return True, filtered[0][0], filtered[0][1], "budget_identity_filtered"
            return False, [], None, "ambiguous_budget_identity"
    candidates = _candidate_rows_by_identity(final_result, patch)
    if len(candidates) == 1: return True, candidates[0][0], candidates[0][1], "identity_unique"
    if len(candidates) > 1:
        target_page = int(patch.get("page") or 0); row_group = str(patch.get("row_group") or "")
        filtered=[]
        for p, r in candidates:
            page_ok = not target_page or int(r.get("page_hint") or r.get("pagina") or target_page) == target_page
            group_ok = not row_group or row_group in [str(x) for x in p]
            if page_ok and group_ok: filtered.append((p,r))
        if len(filtered) == 1: return True, filtered[0][0], filtered[0][1], "identity_filtered"
        return False, [], None, "ambiguous_identity"
    return False, [], None, "target_not_found"

def apply_recovery_patches(final_result: Dict[str, Any], recovery_payload: Dict[str, Any], *, min_confidence: float = 0.85) -> Dict[str, Any]:
    final_result = copy.deepcopy(final_result or {}); recovery_payload = copy.deepcopy(recovery_payload or {})
    patches = list(recovery_payload.get("patches") or []); commits=[]; rejected=[]
    for patch in patches:
        if not isinstance(patch, dict): continue
        target_id = patch.get("target_id") or ".".join(map(str, patch.get("path") or [])); confidence=float(patch.get("confidence") or 0.0)
        field=normalize_field_name(patch.get("field") or "descricao"); value=_clean_text(patch.get("value")); issue=str(patch.get("issue") or patch.get("target_issue") or "")
        base={"target_id":target_id,"field":field,"confidence":confidence,"codigo":patch.get("codigo"),"banco":patch.get("banco"),"source":patch.get("source") or "normalizer_targeted_recovery","page":patch.get("page"),"path":patch.get("path") or []}
        if confidence < min_confidence: rejected.append({**base,"status":"rejected","reason":"confidence_below_threshold"}); continue
        ok,row_path,row,resolution = _resolve_patch_target(final_result, {**patch, "field": field})
        if not ok or row is None: rejected.append({**base,"status":"failed","reason":resolution}); continue
        validation = validate_patch_candidate(field, value, row, {"evidence": patch.get("evidence") or {}})
        if not validation.get("ok"):
            rejected.append({**base,"status":"rejected","reason":f"invalid_{candidate_kind(field)}_value","validation":validation,"value":value}); continue
        normalized_value = _clean_text(validation.get("normalized", value))
        if candidate_kind(field) == "description" and not _value_is_valid_description(normalized_value):
            rejected.append({**base,"status":"rejected","reason":"invalid_description_value","value":normalized_value}); continue
        current=row.get(field)
        if _norm(current) == _norm(normalized_value):
            rejected.append({**base,"status":"rejected","reason":"no_op_same_value","before":current,"value":normalized_value,"resolved_path":row_path}); continue
        if not _current_allows_generic_patch(field,current,normalized_value,issue,patch.get("evidence") or {}):
            rejected.append({**base,"status":"rejected","reason":"current_value_not_empty_or_not_suspect","before":current,"value":normalized_value,"resolved_path":row_path}); continue
        full_path=row_path+[field]; set_ok,before,_=_set_path(final_result,full_path,normalized_value)
        if not set_ok: rejected.append({**base,"status":"failed","reason":"write_failed","resolved_path":row_path}); continue
        verified_ok,after=_get_path(final_result,full_path)
        if not verified_ok or _clean_text(after)!=normalized_value:
            rejected.append({**base,"status":"failed_not_persisted","reason":"verification_failed","before":before,"expected":normalized_value,"actual":after,"resolved_path":row_path}); continue
        if candidate_kind(field) == "description":
            post_veto = pollution_reason(after)
            if post_veto:
                _set_path(final_result, full_path, before)
                rejected.append({**base,"status":"rolled_back","reason":"post_validation_pollution","pollution_reason":post_veto,"before":before,"value":normalized_value,"resolved_path":row_path}); continue
        commits.append({**base,"status":"committed","resolution":resolution,"resolved_path":full_path,"before":before,"after":after,"verified_after_write":True,"post_validation":"ok","validation":validation,"evidence":patch.get("evidence") or {}})
    return {"final_result":final_result,"commits":commits,"rejected":rejected,"received":len(patches)}

def rebuild_correction_document(final_result: Dict[str, Any], *, version: str | None = None, preliminary: Dict[str, Any] | None = None, recovery_audit: Dict[str, Any] | None = None) -> Dict[str, Any]:
    version = version or CURRENT_RELEASE
    doc,_occ = build_correction_document(final_result.get("composicoes") or {}, version=version)
    repair_summary = ((final_result.get("documento_correcao") or {}).get("docling_usage") or {})
    try: doc = augment_correction_with_repair_summary(doc, repair_summary)
    except Exception: pass
    if recovery_audit is not None: doc["targeted_recovery"] = recovery_audit
    gate = ((final_result.get("auditoria_final") or {}).get("quality_gate") or {}) if isinstance(final_result.get("auditoria_final"), dict) else {}
    if isinstance(gate, dict) and gate.get("issues"):
        doc["quality_gate"] = gate
        doc.setdefault("warnings", [])
        if isinstance(doc.get("warnings"), list):
            for issue in list(gate.get("issues") or [])[:100]:
                doc["warnings"].append({"tipo": "quality_gate_issue", **(issue if isinstance(issue, dict) else {"message": str(issue)})})
        resumo = doc.setdefault("resumo", {})
        if isinstance(resumo, dict):
            resumo["total_quality_gate_issues"] = len(gate.get("issues") or [])
            resumo["quality_gate_ok"] = bool(gate.get("ok"))
            if not gate.get("ok"):
                resumo["total_registros_com_erro"] = max(int(resumo.get("total_registros_com_erro") or 0), 1)
    if preliminary is not None:
        doc.setdefault("audit", {})["correction_preliminary_resumo"] = preliminary.get("resumo") or {}
        doc["correction_preliminary_resumo"] = preliminary.get("resumo") or {}
    return doc



def _sync_validation_summary_with_correction(final_result: Dict[str, Any]) -> None:
    """Keep final.validation summary coherent after targeted recovery.

    Correction is the final composition-health artifact.  Older stage summaries may
    still contain preliminary composition errors that were fixed by local PyMuPDF
    recovery.  When correction is clean, downgrade only composition-related error
    occurrences that are known to be pre-recovery artifacts.
    """
    try:
        doc_resumo = ((final_result.get("documento_correcao") or {}).get("resumo") or {})
        if int(doc_resumo.get("total_registros_com_erro") or 0) != 0:
            return
        validacao = final_result.setdefault("validacao", {})
        occ = list(validacao.get("ocorrencias") or [])
        filtered = []
        removed = 0
        stale_codes = {"composicao_campos_vazios", "campos_vazios", "composicao_divergencia_matematica", "divergencia_matematica"}
        for o in occ:
            code = str((o or {}).get("codigo") or "").strip()
            sev = str((o or {}).get("severidade") or "").strip().lower()
            cat = str((o or {}).get("categoria") or "").strip().lower()
            if sev == "erro" and (code in stale_codes or cat == "composicoes"):
                removed += 1
                continue
            filtered.append(o)
        if removed:
            validacao["ocorrencias"] = filtered
        resumo = validacao.setdefault("resumo", {})
        total_erros = sum(1 for o in filtered if str((o or {}).get("severidade") or "").lower() == "erro")
        total_avisos = sum(1 for o in filtered if str((o or {}).get("severidade") or "").lower() == "aviso")
        total_infos = sum(1 for o in filtered if str((o or {}).get("severidade") or "").lower() == "info")
        resumo.update({"total_ocorrencias": len(filtered), "total_erros": total_erros, "total_avisos": total_avisos, "total_infos": total_infos, "tem_erros": total_erros > 0})
        validacao["correction_sync"] = {"status": "synced", "removed_pre_recovery_composition_errors": removed}
    except Exception:
        return

def apply_targeted_recovery_to_final_result(final_result: Dict[str, Any], recovery_payload: Dict[str, Any], *, version: str | None = None, min_confidence: float = 0.85) -> Dict[str, Any]:
    preliminary = copy.deepcopy((final_result or {}).get("documento_correcao") or {})
    applied = apply_recovery_patches(final_result, recovery_payload, min_confidence=min_confidence)
    final=prune_runtime_only_fields(applied["final_result"]); recovery_audit=copy.deepcopy(recovery_payload or {})
    recovery_audit.update({"received":applied["received"],"committed":len(applied["commits"]),"verified":sum(1 for c in applied["commits"] if c.get("verified_after_write")),"failed":len(applied["rejected"]),"commits":applied["commits"],"rejected":applied["rejected"],"applied":len(applied["commits"]),"attempted":bool(recovery_payload.get("attempted",True)),"commit_status":"ok" if not applied["rejected"] else "partial"})
    final.setdefault("meta", {})["targeted_recovery"] = recovery_audit
    final["documento_correcao"] = rebuild_correction_document(final, version=version, preliminary=preliminary, recovery_audit=recovery_audit)
    # v61.0.39: recovery patches can close numeric/unit fields. Re-run the
    # closure engine so correction_document reflects the final state rather than
    # stale pre-recovery unresolved rows.
    if applied["commits"]:
        try:
            from app.parser.line_certainty_closure import run_line_certainty_closure_engine
            final, closure_report = run_line_certainty_closure_engine(final, apply=True, max_rounds=8)
            final.setdefault("meta", {}).setdefault("performance", {})["line_certainty_closure_after_recovery"] = closure_report
            recovery_audit["line_certainty_reclosed_after_recovery"] = True
            final.setdefault("meta", {})["targeted_recovery"] = recovery_audit
            if isinstance(final.get("documento_correcao"), dict):
                final["documento_correcao"]["targeted_recovery"] = recovery_audit
        except Exception as exc:
            recovery_audit["line_certainty_reclosed_after_recovery"] = False
            recovery_audit["line_certainty_reclosure_error"] = {"message": str(exc), "type": exc.__class__.__name__}
    final=prune_runtime_only_fields(final)
    _sync_validation_summary_with_correction(final)
    return final

def apply_targeted_recovery_json(final_json: str, recovery_json: str, options_json: str = "") -> str:
    try:
        final_result=json.loads(final_json or "{}"); recovery_payload=json.loads(recovery_json or "{}"); options=json.loads(options_json or "{}") if options_json else {}
        version=str(options.get("version") or options.get("contract_version") or CURRENT_RELEASE)
        min_conf=float((options.get("parser_contract") or {}).get("targeted_recovery_min_confidence") or recovery_payload.get("apply_confidence_min") or 0.85)
        result=apply_targeted_recovery_to_final_result(final_result,recovery_payload,version=version,min_confidence=min_conf)
        return json.dumps(result,ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status":"error","error":{"code":"targeted_recovery_commit_failed","message":str(exc),"detail":{"exception_type":exc.__class__.__name__}}},ensure_ascii=False)
