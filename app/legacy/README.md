# Legacy Pipeline (Deprecated)

**Status:** Isolated — not used by live API routes.

## Contents

| File | Role |
|------|------|
| `pdf_extractor.py` | Regex/heuristic PDF field extraction |
| `ieee_jats.py` | Hardcoded JATS XML generation (bypasses template schema) |
| `pdf_processor.py` | MongoDB background worker for old `/api/conversions` flow |

## Why kept

Reference for JATS tag-mapping logic not yet ported to the template-driven
`xml_generator` (Phase 3).  Do not import from `app.legacy` in new code.

## Live pipeline

```
PDF → text_extractor → document_pipeline → SemanticDocument (IR)
    → scope_resolver → llm_semantic_mapper → xml_generator
```
