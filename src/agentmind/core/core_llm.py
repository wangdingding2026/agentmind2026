"""Core LLM Provider — 底层 LLM 调用 + 原子事实提取

复用 OpenAI 兼容 chat API。上层的分发/路由决策由 routing.strategies.LLMRoutingStrategy 负责。
"""

import asyncio
import json
import logging

import httpx
import yaml

from agentmind.storage.db import CONFIG_DIR

logger = logging.getLogger("agentmind")

_CORE_LLM_SEMAPHORE = asyncio.Semaphore(3)


def _load_core_llm_cfg() -> dict:
    """读取 core_llm 配置"""
    path = CONFIG_DIR / "settings.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return {}
        cfg = data.get("core_llm", {})
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


async def core_llm_chat(messages: list[dict], temperature: float = 0.3) -> str | None:
    """通用 OpenAI 兼容 chat 调用。失败返回 None"""
    cfg = _load_core_llm_cfg()
    if not cfg.get("enabled") or not cfg.get("endpoint"):
        return None

    endpoint = cfg["endpoint"]
    if "/chat/completions" not in endpoint:
        endpoint = endpoint.rstrip("/") + "/v1/chat/completions"

    async with _CORE_LLM_SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=cfg.get("timeout_seconds", 10)) as client:
                resp = await client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {cfg.get('api_key', '')}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cfg.get("model", ""),
                        "messages": messages,
                        "temperature": temperature,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            logger.debug("Core LLM 调用失败: %s", e)
    return None


_EXTRACT_SYSTEM_PROMPT = """从对话中提取结构化事实。每条事实必须是不可再分的原子单元。
type 取值为：knowledge（知识）、preference（偏好）、decision（决策）。

返回 JSON：
{"facts": [{"fact": "...", "type": "knowledge"}, ...]}

如果对话中没有可提取的事实，返回 {"facts": []}。只返回 JSON，不要其他内容。"""


async def extract_atomic_facts(user_msg: str, agent_response: str) -> list[dict] | None:
    """从一次对话中提取原子事实。失败返回 None"""
    text = f"用户问：「{user_msg[:1000]}」\nAgent 回复：「{agent_response[:2000]}」"
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await core_llm_chat(messages, temperature=0.1)
    if not raw:
        return None
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0] if "```" in raw else raw
        data = json.loads(raw)
        facts = data.get("facts", [])
        return facts if isinstance(facts, list) else None
    except (json.JSONDecodeError, AttributeError):
        logger.debug("原子事实提取 JSON 解析失败: %s", raw[:200])
        return None
