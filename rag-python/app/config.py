from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    app_dir = Path(__file__).resolve().parents[1]
    repo_root = app_dir.parent
    root_env = repo_root / ".env"
    service_env = app_dir / ".env"
    if root_env.exists():
        load_dotenv(root_env, override=False)
    if service_env.exists():
        load_dotenv(service_env, override=True)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


@dataclass
class Settings:
    host: str
    port: int

    internal_token: str
    java_callback_url: str
    java_callback_token: str

    kafka_bootstrap_servers: str
    kafka_ingest_topic: str
    kafka_dlt_topic: str
    kafka_group_id: str
    kafka_max_retries: int

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool

    es_host: str
    es_port: int
    es_scheme: str
    es_username: str
    es_password: str
    es_index_name: str
    es_verify_certs: bool

    embedding_api_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_dimension: int
    embedding_batch_size: int
    embedding_timeout_seconds: int
    embedding_allow_local_fallback: bool

    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int

    chunk_size: int
    chunk_overlap: int
    query_default_top_k: int
    query_max_top_k: int

    @classmethod
    def load(cls) -> "Settings":
        _load_env()
        llm_base = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
        callback_base = os.getenv("RAG_JAVA_CALLBACK_BASE_URL", "http://localhost:8081")
        callback_path = os.getenv("RAG_JAVA_CALLBACK_PATH", "/api/v1/internal/rag/callback/ingest")
        return cls(
            host=os.getenv("RAG_PYTHON_HOST", "0.0.0.0"),
            port=int(os.getenv("RAG_PYTHON_PORT", "18080")),
            internal_token=os.getenv("RAG_PYTHON_INTERNAL_TOKEN", "change-me"),
            java_callback_url=_join_url(callback_base, callback_path),
            java_callback_token=os.getenv("RAG_CALLBACK_TOKEN", "change-me"),
            kafka_bootstrap_servers=os.getenv("SPRING_KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
            kafka_ingest_topic=os.getenv("SPRING_KAFKA_TOPIC_RAG_INGEST", "rag-ingest-topic"),
            kafka_dlt_topic=os.getenv("SPRING_KAFKA_TOPIC_RAG_DLT", "rag-ingest-dlt"),
            kafka_group_id=os.getenv("RAG_KAFKA_GROUP_ID", "rag-python-ingest-group"),
            kafka_max_retries=int(os.getenv("RAG_KAFKA_MAX_RETRIES", "3")),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            minio_bucket=os.getenv("MINIO_BUCKET_NAME", "uploads"),
            minio_secure=_get_bool("MINIO_SECURE", False),
            es_host=os.getenv("ELASTICSEARCH_HOST", "localhost"),
            es_port=int(os.getenv("ELASTICSEARCH_PORT", "9200")),
            es_scheme=os.getenv("ELASTICSEARCH_SCHEME", "http"),
            es_username=os.getenv("ELASTICSEARCH_USERNAME", "elastic"),
            es_password=os.getenv("ELASTICSEARCH_PASSWORD", ""),
            es_index_name=os.getenv("RAG_ES_INDEX", "knowledge_base"),
            es_verify_certs=not _get_bool("ELASTICSEARCH_INSECURE_TRUST_ALL_CERTIFICATES", True),
            embedding_api_url=os.getenv("EMBEDDING_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            embedding_api_key=os.getenv("EMBEDDING_API_KEY", ""),
            embedding_model=os.getenv("EMBEDDING_API_MODEL", "text-embedding-v4"),
            embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
            embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
            embedding_timeout_seconds=int(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60")),
            embedding_allow_local_fallback=_get_bool("EMBEDDING_ALLOW_LOCAL_FALLBACK", False),
            llm_api_url=llm_base,
            llm_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            llm_model=os.getenv("DEEPSEEK_API_MODEL", "deepseek-chat"),
            llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "900")),
            chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "120")),
            query_default_top_k=int(os.getenv("RAG_QUERY_DEFAULT_TOP_K", "8")),
            query_max_top_k=int(os.getenv("RAG_QUERY_MAX_TOP_K", "30")),
        )
