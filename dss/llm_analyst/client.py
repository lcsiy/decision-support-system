"""LLM 客户端 — 轻量封装，读取本项目 .env 的 LLM 配置。"""

import os
import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# 独立加载 .env（项目根），不依赖 dss.config 先被 import —— 保证模块可单独使用
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / '.env')


def _llm_config():
    """读取 LLM 配置。

    优先使用 DSS_* 前缀（本项目独立配置）；未设置时兼容旧的
    TRADINGAGENTS_* 变量名。
    """
    provider = os.environ.get("DSS_LLM_PROVIDER",
                              os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "deepseek"))
    model = os.environ.get("DSS_QUICK_THINK_LLM",
                           os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-chat"))
    backend_url = (os.environ.get("DSS_LLM_BACKEND_URL",
                                  os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL", ""))).strip()
    api_key = ""

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not backend_url:
            backend_url = "https://api.deepseek.com"
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
    elif provider == "openai_compatible":
        api_key = os.environ.get("OPENAI_COMPATIBLE_API_KEY", "")
    else:
        # Try common env vars
        api_key = (
            os.environ.get(f"{provider.upper()}_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", "")
        )

    return {
        "model": model,
        "api_key": api_key,
        "base_url": backend_url or None,
    }


def swing_llm(temperature: float = 0.3) -> ChatOpenAI:
    """返回短线分析用的 ChatOpenAI 实例。

    DeepSeek / OpenAI / Ollama / openai_compatible 均通过 langchain_openai 统一调用。
    """
    cfg = _llm_config()
    kwargs = {
        "model": cfg["model"],
        "temperature": temperature,
    }
    if cfg["api_key"]:
        kwargs["api_key"] = cfg["api_key"]
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    return ChatOpenAI(**kwargs)


def ask_json(llm: ChatOpenAI, system: str, prompt: str) -> dict:
    """向 LLM 发送 system + user 消息，并解析返回的 JSON。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        text = response.content if hasattr(response, "content") else str(response)

        # Strip markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("LLM JSON parse failed: %s", e)
        return {"error": "json_parse_failed", "detail": str(e), "raw": text[:500] if 'text' in dir() else ""}
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return {"error": "llm_call_failed", "detail": str(e)}
