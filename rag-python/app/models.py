from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field


class RagIngestTask(BaseModel):
    taskId: str
    docId: str
    version: int
    fileName: str
    bucket: str
    objectKey: str
    filePath: str
    userId: str
    orgTag: str
    isPublic: bool = Field(default=False, validation_alias=AliasChoices("isPublic", "public"))


class IngestCallbackPayload(BaseModel):
    taskId: str | None = None
    docId: str | None = None
    status: str
    chunkCount: int | None = None
    embeddingTokens: int | None = None
    modelVersion: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    topK: int | None = None
    chatId: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    userId: str | None = None
    username: str | None = None
    role: str | None = None
    allowedOrgTags: list[str] = Field(default_factory=list)
    allowPublic: bool = True


class RagSource(BaseModel):
    fileMd5: str
    fileName: str = ""
    chunkId: int
    pageNumber: int | None = None
    anchorText: str = ""
    score: float
    retrievalMode: str = "VECTOR"
    snippet: str


class RagQueryResponse(BaseModel):
    answer: str
    sources: list[RagSource]
    usage: dict[str, int | str] = Field(default_factory=dict)
