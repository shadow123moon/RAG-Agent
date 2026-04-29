# rag-python

Python RAG worker/service for PaiSmart v1.

It provides:
- Kafka consume from `rag-ingest-topic`
- Document parse + chunk + embedding + Elasticsearch index
- Callback to Java `/api/v1/internal/rag/callback/ingest`
- Internal query API `/internal/v1/query` (protected by `X-Internal-Token`)

## 1. Install

```powershell
cd E:\PaiSmart-main\PaiSmart-main\rag-python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Configure

The service reads environment variables from:
1. Project root `.env`
2. `rag-python/.env` (optional, overrides root values)

Required keys:
- `RAG_PYTHON_INTERNAL_TOKEN`
- `RAG_CALLBACK_TOKEN`
- `SPRING_KAFKA_BOOTSTRAP_SERVERS`
- `SPRING_KAFKA_TOPIC_RAG_INGEST`
- `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`
- `ELASTICSEARCH_HOST`, `ELASTICSEARCH_PORT`, `ELASTICSEARCH_SCHEME`
- `EMBEDDING_API_KEY` (production indexing/query requires a real embedding service)

Optional:
- `EMBEDDING_API_URL`, `EMBEDDING_API_MODEL`, `EMBEDDING_DIMENSION`
- `EMBEDDING_ALLOW_LOCAL_FALLBACK=true` enables deterministic hash embeddings for local development only
- `DEEPSEEK_API_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_API_MODEL`
- `RAG_QUERY_DEFAULT_TOP_K`, `RAG_QUERY_MAX_TOP_K`

## 3. Run

```powershell
cd E:\PaiSmart-main\PaiSmart-main\rag-python
.\.venv\Scripts\Activate.ps1
python -m app.main
```

Default listen address:
- `http://0.0.0.0:18080`

## 4. Health

- `GET /health/live`
- `GET /health/ready`
