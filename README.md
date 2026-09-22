# IEEE XML Converter — Backend

FastAPI service for schema-adaptive PDF → XML conversion (default LLM: **Anthropic Claude**).

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # set ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

## Demo

```bash
python scripts/demo.py
```
