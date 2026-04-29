from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings
from .models import RagSource

logger = logging.getLogger(__name__)


class LlmAnswerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def generate_general_answer(self, query: str, technical: bool) -> str:
        if not self._settings.llm_api_key:
            if technical:
                return (
                    "未检索到知识库来源，以下为通用技术回答：\n\n"
                    "当前大模型接口不可用，无法生成完整通用回答。建议换一个更贴近知识库的问题，"
                    "或者稍后在模型服务恢复后重试。"
                )
            return "你好，我是派聪明。你可以问我和已上传知识库相关的问题，我会尽量引用来源回答。"

        system_prompt = (
            "你是一个后端技术问答助手。当前没有检索到可引用的知识库来源。"
            "如果是技术问题，可以基于通用技术知识回答，但必须在开头明确说明“未检索到知识库来源”。"
            "如果不是技术问题，简短友好回应，并引导用户询问知识库相关问题。"
        )
        if technical:
            user_prompt = (
                f"问题：{query}\n\n"
                "请给出通用技术回答。要求：\n"
                "1. 开头必须写：未检索到知识库来源，以下为通用技术回答。\n"
                "2. 先给结论，再分点解释。\n"
                "3. 如果适合面试，补一段“面试可以这样说”。\n"
                "4. 不要伪造来源，不要说来自知识库。"
            )
            max_tokens = 1200
        else:
            user_prompt = (
                f"用户输入：{query}\n\n"
                "请简短友好回应，并说明可以基于已上传知识库回答技术问题。"
            )
            max_tokens = 300

        return await self._chat_completion(system_prompt, user_prompt, max_tokens=max_tokens)

    async def generate_answer(self, query: str, sources: list[RagSource]) -> str:
        if not sources:
            return "暂无相关信息。"
        if not self._settings.llm_api_key:
            return self._build_fallback_answer(sources)

        context_lines: list[str] = []
        for idx, source in enumerate(sources, start=1):
            page = f" | 第{source.pageNumber}页" if source.pageNumber else ""
            context_lines.append(
                f"[来源#{idx}: {source.fileName or source.fileMd5}{page}] {source.snippet}"
            )
        context = "\n".join(context_lines)

        system_prompt = (
            "你是一个偏后端面试讲解风格的知识库问答助手。"
            "请使用简体中文回答，必须优先依据给定上下文，不要编造上下文没有的信息。"
            "如果上下文只覆盖部分内容，可以明确说明“知识库中能确认的是...”。"
            "如果上下文完全不足，请明确回答“暂无相关信息”。"
            "不要在回答末尾单独输出参考来源列表，系统会单独展示可点击来源。"
        )
        user_prompt = (
            f"问题：{query}\n\n"
            f"可用上下文：\n{context}\n\n"
            "输出要求：\n"
            "1. 先给一句明确结论。\n"
            "2. 再用 3 到 6 个要点展开解释，每个要点要有机制、原因或流程，不要只写标题。\n"
            "3. 如果问题适合面试回答，补一段“面试可以这样说”。\n"
            "4. 如果有容易混淆的点，补一段“注意点”。\n"
            "5. 回答默认不少于 500 字；如果用户要求“详细点/展开讲/面试版”，不少于 800 字。\n"
            "6. 不要堆砌来源清单，不要在末尾输出参考文献列表。"
        )

        return await self._chat_completion(system_prompt, user_prompt, max_tokens=1600, sources=sources)

    async def _chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        sources: list[RagSource] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        url = self._settings.llm_api_url.rstrip("/") + "/chat/completions"
        timeout = httpx.Timeout(self._settings.llm_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    return self._build_fallback_answer(sources) if sources else "暂无相关信息。"
                content = choices[0].get("message", {}).get("content", "")
                if not content:
                    return self._build_fallback_answer(sources) if sources else "暂无相关信息。"
                return str(content).strip()
        except Exception as exc:
            logger.warning("LLM answer generation failed, using fallback answer: %s", exc)
            return self._build_fallback_answer(sources) if sources else "暂无相关信息。"

    @staticmethod
    def _build_fallback_answer(sources: list[RagSource]) -> str:
        top = sources[:3]
        parts = [f"{i + 1}. {item.snippet[:240]}" for i, item in enumerate(top)]
        return (
            "根据知识库命中的片段，可以先确认以下内容：\n"
            + "\n".join(parts)
            + "\n\n这些片段已经提供了回答问题的核心依据，但当前大模型接口不可用，所以这里只做基于片段的整理。"
        )
