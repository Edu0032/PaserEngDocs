# Evidence Grade Closure Engine — v61.0.40

A linha só deve ser considerada `closed_100` quando cada campo obrigatório tem evidência rastreável.

## Graus de evidência

- `physical_pdf_evidence`
- `physical_pdf_evidence_math_confirmed`
- `extracted_cross_evidence`
- `extracted_cross_evidence_math_confirmed`
- `math_confirmed_existing_value`
- `math_only_expected`
- `weak_candidate`
- `unresolved`

## Matemática

A matemática calcula o valor esperado, salva em `_calc`, e guia a busca. Ela não publica valores sozinha.

Exemplo:

```json
{
  "total": "",
  "_calc": {
    "math_only_expectations": [
      {
        "field": "total",
        "expected_value": "14,27",
        "public_write_allowed": false
      }
    ]
  }
}
```
