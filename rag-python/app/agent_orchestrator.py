from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .embedding import EmbeddingService
from .es_store import ElasticsearchStore
from .llm import LlmAnswerService
from .models import RagQueryRequest, RagQueryResponse, RagSource

logger = logging.getLogger(__name__)


TECHNICAL_QUERY_PATTERN = re.compile(
    r"(java|python|redis|mysql|kafka|spring|springboot|docker|linux|nginx|"
    r"jvm|jpa|mybatis|http|tcp|ip|线程|进程|锁|事务|索引|缓存|数据库|"
    r"消息队列|分布式|微服务|后端|接口|算法|数据结构|持久化|内存|"
    r"并发|高并发|性能|优化|架构|es|elasticsearch|minio|rag|向量|"
    r"embedding|大模型|知识库|agent|检索|分片|上传|限流)",
    re.IGNORECASE,
)
GREETING_PATTERN = re.compile(
    r"^(你好|您好|hello|hi|hey|在吗|哈喽|嗨|早上好|晚上好)[！!。.\s]*$",
    re.IGNORECASE,
)
FOLLOW_UP_PATTERN = re.compile(
    r"^(再)?(详细|展开|细说|继续|这个|它|上面|前面|为什么|怎么做|怎么实现|原理|流程)",
    re.IGNORECASE,
)
STOPWORDS = {"这个", "那个", "它", "上面", "前面", "再详细点", "详细点", "继续"}
KEYWORD_STOPWORDS = {
    "什么",
    "是什么",
    "为什么",
    "怎么",
    "如何",
    "区别",
    "原理",
    "流程",
    "面试",
    "面试版",
    "详细",
    "展开",
    "讲一下",
    "说一下",
    "后端",
    "技术",
    "项目",
    "这个",
    "那个",
}
TECHNICAL_KEYWORDS = (
    "redis",
    "mysql",
    "kafka",
    "spring",
    "springboot",
    "docker",
    "linux",
    "nginx",
    "jvm",
    "jpa",
    "mybatis",
    "http",
    "tcp",
    "kubernetes",
    "informer",
    "minio",
    "elasticsearch",
    "faiss",
    "rag",
    "embedding",
    "agent",
    "aof",
    "rdb",
    "io",
    "api",
    "混合持久化",
    "持久化",
    "内存",
    "单线程",
    "多线程",
    "网络",
    "多路复用",
    "跳表",
    "压缩列表",
    "消息队列",
    "分布式",
    "微服务",
    "索引",
    "缓存",
    "事务",
    "锁",
    "线程",
    "进程",
    "向量",
    "知识库",
    "检索",
    "分片",
    "上传",
    "限流",
)


class Intent(str, Enum):
    GREETING = "greeting"
    KNOWLEDGE_QUERY = "knowledge_query"
    GENERAL_TECHNICAL = "general_technical"
    UNKNOWN = "unknown"


@dataclass
class AgentPlan:
    intent: Intent
    original_query: str
    retrieval_query: str
    top_k: int
    allow_fallback: bool
    steps: list[str] = field(default_factory=list)
    evidence_enough: bool = False
    fallback_mode: str = "none"


class AgentOrchestrator:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        es_store: ElasticsearchStore,
        llm_service: LlmAnswerService,
        default_top_k: int,
        max_top_k: int,
    ) -> None:
        self._embedding_service = embedding_service
        self._es_store = es_store
        self._llm_service = llm_service
        self._default_top_k = default_top_k
        self._max_top_k = max_top_k

    async def answer(self, request: RagQueryRequest) -> RagQueryResponse:
        plan = self._build_plan(request)
        usage: dict[str, int | str] = {
            "intent": plan.intent.value,
            "retrievalQuery": plan.retrieval_query,
            "agentSteps": " -> ".join(plan.steps),
        }

        if plan.intent == Intent.GREETING:
            answer = await self._llm_service.generate_general_answer(request.query, technical=False)
            usage["fallbackMode"] = "chat"
            usage["retrievedChunks"] = 0
            return RagQueryResponse(answer=answer, sources=[], usage=usage)

        vectors, embedding_tokens, embedding_model = await self._embedding_service.embed_texts([plan.retrieval_query])
        usage["queryEmbeddingTokens"] = embedding_tokens
        usage["embeddingModel"] = embedding_model
        if not vectors:
            return await self._fallback(request, plan, usage, reason="embedding_empty")

        sources = await self._search_with_repair(request, plan, vectors[0], usage)
        usage["retrievedChunks"] = len(sources)

        if sources:
            answer = await self._llm_service.generate_answer(request.query, sources)
            usage["fallbackMode"] = "knowledge"
            usage["evidenceEnough"] = "true" if plan.evidence_enough else "partial"
            usage["agentSteps"] = " -> ".join(plan.steps)
            return RagQueryResponse(answer=answer, sources=sources, usage=usage)

        return await self._fallback(request, plan, usage, reason="no_sources")

    def _build_plan(self, request: RagQueryRequest) -> AgentPlan:
        query = request.query.strip()
        intent = self._classify_intent(query)
        top_k = request.topK if request.topK is not None else self._default_top_k
        top_k = max(1, min(top_k, self._max_top_k))
        retrieval_query = self._rewrite_query(query, request.history)
        plan = AgentPlan(
            intent=intent,
            original_query=query,
            retrieval_query=retrieval_query,
            top_k=top_k,
            allow_fallback=intent in {Intent.GENERAL_TECHNICAL, Intent.KNOWLEDGE_QUERY},
        )
        plan.steps.append(f"classify:{intent.value}")
        if retrieval_query != query:
            plan.steps.append("rewrite_query")
        return plan

    async def _search_with_repair(
        self,
        request: RagQueryRequest,
        plan: AgentPlan,
        query_vector: list[float],
        usage: dict[str, int | str],
    ) -> list[RagSource]:
        try:
            plan.steps.append("retrieve:first_pass")
            sources = await self._search(request, plan.retrieval_query, query_vector, plan.top_k)
        except Exception as exc:
            logger.warning("Agent first-pass retrieval failed: %s", exc)
            sources = []

        if self._evidence_enough(plan.retrieval_query, sources):
            plan.evidence_enough = True
            plan.steps.append("judge:evidence_enough")
            return sources

        plan.steps.append("judge:evidence_weak")
        repaired_query = self._repair_query(plan.retrieval_query)
        if repaired_query == plan.retrieval_query:
            return []

        try:
            vectors, repair_tokens, _ = await self._embedding_service.embed_texts([repaired_query])
            usage["repairEmbeddingTokens"] = repair_tokens
            if not vectors:
                return []
            plan.steps.append("retrieve:query_repair")
            repaired_sources = await self._search(request, repaired_query, vectors[0], plan.top_k)
            if self._evidence_enough(repaired_query, repaired_sources):
                usage["repairedQuery"] = repaired_query
                plan.retrieval_query = repaired_query
                plan.evidence_enough = True
                plan.steps.append("judge:repaired_evidence_enough")
                return repaired_sources
        except Exception as exc:
            logger.warning("Agent query repair retrieval failed: %s", exc)

        # Weak hits are treated as no evidence to avoid attaching irrelevant knowledge-base sources.
        return []

    async def _search(
        self,
        request: RagQueryRequest,
        query: str,
        query_vector: list[float],
        top_k: int,
    ) -> list[RagSource]:
        return await asyncio.to_thread(
            self._es_store.search,
            query,
            query_vector,
            top_k,
            request.userId,
            request.allowedOrgTags,
            request.allowPublic,
        )

    async def _fallback(
        self,
        request: RagQueryRequest,
        plan: AgentPlan,
        usage: dict[str, int | str],
        reason: str,
    ) -> RagQueryResponse:
        plan.steps.append(f"fallback:{reason}")
        usage["retrievedChunks"] = 0
        usage["fallbackReason"] = reason
        usage["agentSteps"] = " -> ".join(plan.steps)
        if plan.intent in {Intent.GENERAL_TECHNICAL, Intent.KNOWLEDGE_QUERY} and plan.allow_fallback:
            answer = await self._llm_service.generate_general_answer(request.query, technical=True)
            usage["fallbackMode"] = "general_technical"
        elif plan.intent == Intent.GREETING:
            answer = await self._llm_service.generate_general_answer(request.query, technical=False)
            usage["fallbackMode"] = "chat"
        else:
            answer = "暂无相关信息。"
            usage["fallbackMode"] = "none"
        return RagQueryResponse(answer=answer, sources=[], usage=usage)

    def _classify_intent(self, query: str) -> Intent:
        normalized = query.strip()
        if GREETING_PATTERN.search(normalized):
            return Intent.GREETING
        if TECHNICAL_QUERY_PATTERN.search(normalized):
            return Intent.KNOWLEDGE_QUERY
        question_marks = ("是什么", "为什么", "怎么", "如何", "区别", "原理", "流程", "面试")
        if any(marker in normalized for marker in question_marks) and len(normalized) >= 6:
            return Intent.GENERAL_TECHNICAL
        return Intent.UNKNOWN

    def _rewrite_query(self, query: str, history: list[dict[str, Any]]) -> str:
        normalized = query.strip()
        if not history or not FOLLOW_UP_PATTERN.search(normalized):
            return normalized

        last_user = ""
        for item in reversed(history[-8:]):
            if str(item.get("role", "")).lower() == "user":
                content = str(item.get("content", "")).strip()
                if content and content not in STOPWORDS:
                    last_user = content
                    break
        if not last_user:
            return normalized

        return f"{last_user} {normalized}"

    def _repair_query(self, query: str) -> str:
        repaired = re.sub(r"[？?！!。.,，；;：:]+", " ", query)
        repaired = re.sub(r"\s+", " ", repaired).strip()
        repaired = repaired.replace("再详细点", "").replace("详细点", "").replace("面试版", "")
        return repaired.strip() or query

    def _evidence_enough(self, query: str, sources: list[RagSource]) -> bool:
        if not sources:
            return False
        keywords = self._keywords(query)
        if not keywords:
            return False
        hit_count = 0
        joined = "\n".join(
            " ".join(
                filter(
                    None,
                    [
                        source.snippet,
                        source.fileName,
                        source.fileMd5,
                        source.anchorText,
                    ],
                )
            )
            for source in sources
        ).lower()
        for keyword in keywords:
            if keyword.lower() in joined:
                hit_count += 1
        if hit_count == 0:
            return False
        if len(keywords) == 1:
            return hit_count == 1 and len(sources) >= 1
        return hit_count >= min(2, len(keywords))

    @staticmethod
    def _keywords(query: str) -> list[str]:
        normalized = query.lower()
        candidates: list[str] = []
        candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", query))
        for keyword in TECHNICAL_KEYWORDS:
            if keyword.lower() in normalized:
                candidates.append(keyword)

        result: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            keyword = item.strip()
            key = keyword.lower()
            if len(key) < 2 or key in KEYWORD_STOPWORDS or keyword in STOPWORDS:
                continue
            if key in seen:
                continue
            seen.add(key)
            result.append(keyword)
            if len(result) >= 8:
                break
        return result
