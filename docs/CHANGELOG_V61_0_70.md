# v61.0.70 — from-scratch block inventory and active re-extraction

- Adds compact PDF-first physical block inventory for targeted composition blocks.
- Adds active re-extraction engine driven by coverage targets and existing recovery tools.
- Integrates both stages into the real final integrity orchestrator.
- Keeps final JSON compact: full raw text stays out; summaries and evidence registries remain compact.
- Keeps SICRO engine untouched.

Validation: compileall OK, parser_browser pytest OK, api_docling pytest OK, node checks OK, quality scan OK, zip tests OK.
