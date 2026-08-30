"""LLM Entity Extractor: Uses LLM planning to extract multi-action keys from Vietnamese prompts."""

from __future__ import annotations

import json
import os
import re
from typing import Any
import httpx


class LLMEntityExtractor:
    SYSTEM_PROMPT = ("Avoid explanations. Return JSON array of {name, stt, year, method, all_years}")

    @classmethod
    async def extract_actions(
        cls,
        user_message: str,
        ollama_url: str = "",
        ollama_model: str = "",
    ) -> list[dict[str, Any]]:
        url = (ollama_url or os.getenv("OLLAMA_PORT", "http://localhost:11434")).rstrip("/")
        model = ollama_model or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OLLAMA_API_KEY", "").strip()

        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        messages = [
            {"role": "system", "content": cls.SYSTEM_PROMPT},
            {"role": "user", "content": f"Trich xuat: {user_message}"},
        ]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "format": "json",
                    },
                    headers=headers,
                )
                if res.status_code == 200:
                    text = res.text
                    content = ""
                    # Handle both NDJSON and standard JSON
                    for line in text.strip().split("\n"):
                        if line.strip():
                            try:
                                d = json.loads(line)
                                msg = d.get("message", {}).get("content", "")
                                if msg:
                                    content += msg
                            except Exception:
                                pass
                    content = content.strip()
                    if not content:
                        try:
                            d = res.json()
                            content = d.get("message", {}).get("content", "").strip()
                        except Exception:
                            pass

                    if content.startswith("[") and content.endswith("]"):
                        return json.loads(content)
                    m = re.search(r"\[.*\]", content, re.DOTALL)
                    if m:
                        return json.loads(m.group(0))
        except Exception:
            pass

        return []
