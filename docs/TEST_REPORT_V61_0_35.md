# Test report — v61.0.35

## Commands executed

```text
PYTHONPATH=parser_browser pytest -q
python -m compileall -q parser_browser/app api_docling/app
node --check parser_browser/browser/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/pyodide/pyodide-parser-worker.js
node --check parser_browser/browser/demo/api-pdf-browser.js
python tools/quality_safety_scan.py .
PYTHONPATH=api_docling python base_config merge validation
zip -T api_pdf_v61_0_35_monorepo_candidate_profile_consensus_engine.zip
zip -T lovable_browser_bundle_v61_0_35.zip
```

## Result

```text
89 passed
compileall OK
node --check OK
quality_safety_scan OK
api_docling base_config merge OK
zip integrity OK
```

## New tests added

- Candidate Profile Consensus Engine.
- ANP 01 reverse repair with neighbour-owned fragments.
- Clean short description is kept.
- Candidate containing neighbour description does not replace a clean value.
- User base_config overlay deep merge.
- User base_config validation for custom table columns.

## Real historical JSON smoke test

The engine was also run over the historical v61.0.27 `final_result` artifact. The polluted item:

```text
3.2.7 ANP 01
- EXCLUSIVE ... AQUISIÇÃO ... EXECUÇÃO DE IMPRIMAÇÃO ...
```

was corrected to:

```text
AQUISIÇÃO DE ASFALTO DILUIDO CM-30
```

The correction was explained by neighbour subtraction:

- previous item owned `- EXCLUSIVE ESCAVAÇÃO... AF_09/2024`;
- next item owned `EXECUÇÃO DE IMPRIMAÇÃO... AF_11/2019`;
- remaining text belonged to the target.
