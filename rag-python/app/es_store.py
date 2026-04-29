from __future__ import annotations

from typing import Any

from elasticsearch import Elasticsearch, helpers

from .config import Settings
from .models import RagSource
from .parsers import ParsedChunk


class ElasticsearchStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = Elasticsearch(
            hosts=[
                {
                    "host": settings.es_host,
                    "port": settings.es_port,
                    "scheme": settings.es_scheme,
                }
            ],
            basic_auth=(settings.es_username, settings.es_password) if settings.es_username else None,
            verify_certs=settings.es_verify_certs,
            request_timeout=60,
        )

    def ping(self) -> bool:
        return bool(self._client.ping())

    def delete_by_doc_id(self, doc_id: str) -> None:
        self._client.delete_by_query(
            index=self._settings.es_index_name,
            body={"query": {"term": {"fileMd5": doc_id}}},
            conflicts="proceed",
            refresh=True,
        )

    def delete_by_doc_id_except_version(self, doc_id: str, version: int) -> None:
        self._client.delete_by_query(
            index=self._settings.es_index_name,
            body={
                "query": {
                    "bool": {
                        "must": [{"term": {"fileMd5": doc_id}}],
                        "must_not": [{"term": {"ingestVersion": version}}],
                    }
                }
            },
            conflicts="proceed",
            refresh=True,
        )

    def bulk_upsert(
        self,
        task_id: str,
        doc_id: str,
        version: int,
        file_name: str,
        user_id: str,
        org_tag: str,
        is_public: bool,
        chunks: list[ParsedChunk],
        vectors: list[list[float]],
        model_version: str,
    ) -> int:
        actions: list[dict[str, Any]] = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            doc = {
                "id": f"{doc_id}:{version}:{i}",
                "fileMd5": doc_id,
                "fileName": file_name,
                "chunkId": i,
                "textContent": chunk.content,
                "pageNumber": chunk.page_number,
                "anchorText": chunk.anchor_text,
                "vector": vector,
                "modelVersion": model_version,
                "userId": user_id,
                "orgTag": org_tag,
                "isPublic": is_public,
                "public": is_public,
                "ingestVersion": version,
                "taskId": task_id,
            }
            actions.append(
                {
                    "_index": self._settings.es_index_name,
                    "_id": doc["id"],
                    "_source": doc,
                }
            )
        if not actions:
            return 0
        helpers.bulk(self._client, actions, refresh=True, raise_on_error=True)
        return len(actions)

    def search(
        self,
        query: str,
        query_vector: list[float],
        top_k: int,
        user_id: str | None,
        allowed_org_tags: list[str],
        allow_public: bool,
    ) -> list[RagSource]:
        should_filters: list[dict[str, Any]] = []
        if user_id:
            should_filters.append({"term": {"userId": user_id}})
        if allow_public:
            should_filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"public": True}},
                            {"term": {"isPublic": True}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        if allowed_org_tags:
            should_filters.append({"terms": {"orgTag": allowed_org_tags}})

        if not should_filters:
            # If no visibility scope is given, explicitly return empty.
            return []

        body: dict[str, Any] = {
            "size": top_k,
            "query": {
                "script_score": {
                    "query": {
                        "bool": {
                            "must": [{"match": {"textContent": {"query": query}}}],
                            "filter": [{"bool": {"should": should_filters, "minimum_should_match": 1}}],
                        }
                    },
                    "script": {
                        "source": "cosineSimilarity(params.qv, 'vector') + 1.0",
                        "params": {"qv": query_vector},
                    },
                }
            },
        }

        response = self._client.search(index=self._settings.es_index_name, body=body)
        hits = response.get("hits", {}).get("hits", [])
        sources: list[RagSource] = []
        for hit in hits:
            src = hit.get("_source", {})
            text = str(src.get("textContent", ""))
            sources.append(
                RagSource(
                    fileMd5=str(src.get("fileMd5", "")),
                    fileName=str(src.get("fileName", "")),
                    chunkId=int(src.get("chunkId", 0)),
                    pageNumber=src.get("pageNumber"),
                    anchorText=str(src.get("anchorText", "")),
                    score=float(hit.get("_score", 0.0)),
                    retrievalMode="VECTOR",
                    snippet=text[:800],
                )
            )
        return sources
