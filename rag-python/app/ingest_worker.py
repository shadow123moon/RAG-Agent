from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
from minio import Minio

from .callbacks import JavaCallbackClient
from .config import Settings
from .embedding import EmbeddingService
from .es_store import ElasticsearchStore
from .models import IngestCallbackPayload, RagIngestTask
from .parsers import parse_document

logger = logging.getLogger(__name__)


class IngestWorker:
    def __init__(
        self,
        settings: Settings,
        es_store: ElasticsearchStore,
        embedding_service: EmbeddingService,
        callback_client: JavaCallbackClient,
    ) -> None:
        self._settings = settings
        self._es_store = es_store
        self._embedding_service = embedding_service
        self._callback_client = callback_client
        self._stop_event = asyncio.Event()
        self._runner_task: asyncio.Task[None] | None = None
        self._minio = self._build_minio_client(settings)

    async def start(self) -> None:
        if self._runner_task is None:
            self._runner_task = asyncio.create_task(self._run_forever(), name="rag-ingest-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._runner_task is not None:
            self._runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner_task
            self._runner_task = None

    async def _run_forever(self) -> None:
        while not self._stop_event.is_set():
            consumer: AIOKafkaConsumer | None = None
            producer: AIOKafkaProducer | None = None
            try:
                consumer = AIOKafkaConsumer(
                    self._settings.kafka_ingest_topic,
                    bootstrap_servers=self._settings.kafka_bootstrap_servers,
                    group_id=self._settings.kafka_group_id,
                    value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                    enable_auto_commit=False,
                    auto_offset_reset="earliest",
                )
                producer = AIOKafkaProducer(
                    bootstrap_servers=self._settings.kafka_bootstrap_servers,
                    value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                )
                await consumer.start()
                await producer.start()
                logger.info(
                    "RAG ingest worker started. topic=%s, group=%s",
                    self._settings.kafka_ingest_topic,
                    self._settings.kafka_group_id,
                )
                while not self._stop_event.is_set():
                    batches = await consumer.getmany(timeout_ms=1500, max_records=20)
                    for topic_partition, records in batches.items():
                        for record in records:
                            await self._handle_record(record.value, producer)
                            commit_partition = TopicPartition(
                                topic_partition.topic,
                                topic_partition.partition,
                            )
                            await consumer.commit({commit_partition: record.offset + 1})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("RAG ingest worker loop failed, retrying: %s", exc)
                await asyncio.sleep(3)
            finally:
                if consumer is not None:
                    await consumer.stop()
                if producer is not None:
                    await producer.stop()

    async def _handle_record(self, payload: dict[str, Any], producer: AIOKafkaProducer) -> None:
        try:
            task = RagIngestTask.model_validate(payload)
        except Exception as exc:
            logger.error("Invalid ingest payload, skipping: payload=%s, error=%s", payload, exc)
            await self._send_dlt(producer, payload, "INVALID_PAYLOAD", str(exc))
            return

        await self._safe_callback(
            IngestCallbackPayload(taskId=task.taskId, docId=task.docId, status="INGESTING")
        )

        max_retries = max(1, self._settings.kafka_max_retries)
        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                indexed_count, token_usage, model_version = await self._process_task(task)
                await self._safe_callback(
                    IngestCallbackPayload(
                        taskId=task.taskId,
                        docId=task.docId,
                        status="AVAILABLE",
                        chunkCount=indexed_count,
                        embeddingTokens=token_usage,
                        modelVersion=model_version,
                    )
                )
                logger.info(
                    "RAG ingest success. taskId=%s, docId=%s, version=%s, chunks=%s",
                    task.taskId,
                    task.docId,
                    task.version,
                    indexed_count,
                )
                return
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "RAG ingest attempt failed. taskId=%s, attempt=%s/%s, error=%s",
                    task.taskId,
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(attempt)

        await self._safe_callback(
            IngestCallbackPayload(
                taskId=task.taskId,
                docId=task.docId,
                status="FAILED",
                errorCode="INGEST_FAILED",
                errorMessage=last_error[:1500] if last_error else "unknown error",
            )
        )
        await self._send_dlt(producer, payload, "INGEST_FAILED", last_error)

    async def _process_task(self, task: RagIngestTask) -> tuple[int, int, str]:
        content = await asyncio.to_thread(self._read_file, task.bucket, task.objectKey)
        chunks = await asyncio.to_thread(
            parse_document,
            task.fileName,
            content,
            self._settings.chunk_size,
            self._settings.chunk_overlap,
        )
        if not chunks:
            raise RuntimeError("parsed chunk list is empty")

        vectors, token_usage, model_version = await self._embedding_service.embed_texts(
            [item.content for item in chunks]
        )
        if len(vectors) != len(chunks):
            raise RuntimeError("embedding result count mismatch")

        indexed_count = await asyncio.to_thread(
            self._es_store.bulk_upsert,
            task.taskId,
            task.docId,
            task.version,
            task.fileName,
            task.userId,
            task.orgTag,
            task.isPublic,
            chunks,
            vectors,
            model_version,
        )
        await asyncio.to_thread(self._es_store.delete_by_doc_id_except_version, task.docId, task.version)
        return indexed_count, token_usage, model_version

    def _read_file(self, bucket: str, object_key: str) -> bytes:
        response = self._minio.get_object(bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def _safe_callback(self, payload: IngestCallbackPayload) -> None:
        try:
            await self._callback_client.send(payload)
        except Exception as exc:
            logger.warning("Failed to callback Java, payload=%s, error=%s", payload.model_dump(), exc)

    async def _send_dlt(
        self,
        producer: AIOKafkaProducer,
        payload: dict[str, Any],
        error_code: str,
        error_message: str,
    ) -> None:
        dlt_message = {
            "event": "rag_ingest_failed",
            "errorCode": error_code,
            "errorMessage": (error_message or "")[:2000],
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await producer.send_and_wait(self._settings.kafka_dlt_topic, dlt_message)
        except Exception as exc:
            logger.warning("Failed to produce DLT message: %s", exc)

    @staticmethod
    def _build_minio_client(settings: Settings) -> Minio:
        parsed = urlparse(settings.minio_endpoint)
        if parsed.scheme:
            endpoint = parsed.netloc
            secure = parsed.scheme == "https"
        else:
            endpoint = settings.minio_endpoint
            secure = settings.minio_secure
        return Minio(
            endpoint=endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure,
        )
