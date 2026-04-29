from __future__ import annotations

import httpx

from .config import Settings
from .models import IngestCallbackPayload


class JavaCallbackClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, payload: IngestCallbackPayload) -> None:
        headers = {
            "Content-Type": "application/json",
            "X-Rag-Callback-Token": self._settings.java_callback_token,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
            response = await client.post(
                self._settings.java_callback_url,
                json=payload.model_dump(),
                headers=headers,
            )
            response.raise_for_status()

