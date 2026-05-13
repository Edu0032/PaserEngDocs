from pathlib import Path
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_constants_are_current():
    text = (ROOT / 'parser_browser/app/config/version.py').read_text(encoding='utf-8')
    assert 'v61.0.35-candidate-profile-consensus-engine' in text
    assert '.'.join(['v61','0','16']) not in text


def test_no_stale_v16_release_artifacts_in_project_text_files():
    offenders = []
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.suffix.lower() in {'.zip', '.pdf', '.pyc'}:
            continue
        if any(part in {'__pycache__'} for part in p.parts):
            continue
        try:
            text = p.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        if '.'.join(['v61','0','16']) in text or '_'.join(['v61','0','16']) in text or '_'.join(['V61','0','16']) in text:
            offenders.append(str(p.relative_to(ROOT)))
    assert offenders == []


def test_worker_does_not_depend_on_external_normalizer_api():
    worker = (ROOT / 'parser_browser/browser/pyodide/pyodide-parser-worker.js').read_text(encoding='utf-8')
    assert '127.0.0.1:8001' not in worker
    assert 'callNormalizerLocalRefinePyodide' in worker
    assert 'callNormalizerRecoveryLocalPyodide' in worker
    assert 'refine_table_structure_local_file_json' in worker
    assert 'recover_fields_local_file_json' in worker


def test_sicro_clean_contract_adapter_is_authoritative():
    bridge = (ROOT / 'parser_browser/app/parser/sicro_native_bridge.py').read_text(encoding='utf-8')
    assert 'v61.0.35-candidate-profile-consensus-engine' in bridge
    assert 'sicro_only_v61_0_20' in bridge
    assert 'classification_rule' in bridge or '_native_has_item' in bridge
    assert 'secoes' in bridge


def test_pyodide_source_zip_contains_current_versions():
    zpath = ROOT / 'parser_browser/browser/pyodide/api_pdf_pyodide_src.zip'
    assert zpath.exists()
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
        assert 'app/parser/sicro_native_bridge.py' in names
        assert 'app/sicro_only/sicro_twopass.py' in names
        version_py = zf.read('app/config/version.py').decode('utf-8')
        assert 'v61.0.35-candidate-profile-consensus-engine' in version_py
        assert '.'.join(['v61','0','16']) not in version_py
