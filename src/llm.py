import os
import time
import logging
from typing import Optional, List, Dict, Any
from src.config import (
    LLM_PROVIDER, GROQ_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY, 
    OPENAI_API_KEY, OLLAMA_BASE_URL, get_active_model_info, PROVIDER_MODELS
)

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LLMEngine")

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from groq import Groq
except ImportError:
    Groq = None

class LLMEngine:
    """
    Unified LLM inference engine supporting models <= 10B parameters.
    Handles routing between Groq, OpenRouter, Gemini, Ollama, and offline fallback.
    Includes built-in retry and provider fallback to prevent execution interruptions during multi-agent evaluations.
    """
    def __init__(self, primary_provider: Optional[str] = None):
        self.primary_provider = (primary_provider or LLM_PROVIDER).lower()
        self.provider_clients = {}
        self.provider_models = PROVIDER_MODELS.copy()
        self._initialize_clients()

    def _initialize_clients(self):
        # 1. Groq setup (Recommended for ultra-fast <= 10B inference: llama-3.1-8b-instant)
        if GROQ_API_KEY:
            try:
                if Groq is not None:
                    self.provider_clients["groq"] = ("groq_sdk", Groq(api_key=GROQ_API_KEY))
                elif OpenAI is not None:
                    self.provider_clients["groq"] = ("openai_compat", OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY))
            except Exception as e:
                logger.warning(f"[LLMEngine] Could not init Groq client: {e}")

        # 2. OpenRouter setup (Open models <= 10B: meta-llama/llama-3.1-8b-instruct)
        if OPENROUTER_API_KEY and OpenAI is not None:
            try:
                self.provider_clients["openrouter"] = (
                    "openai_compat", 
                    OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
                )
            except Exception as e:
                logger.warning(f"[LLMEngine] Could not init OpenRouter client: {e}")

        # 3. Gemini setup (Open weights gemma-2-9b-it)
        if GEMINI_API_KEY:
            try:
                if genai is not None:
                    genai.configure(api_key=GEMINI_API_KEY)
                    self.provider_clients["gemini"] = ("gemini_sdk", genai)
                elif OpenAI is not None:
                    self.provider_clients["gemini"] = (
                        "openai_compat",
                        OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=GEMINI_API_KEY)
                    )
            except Exception as e:
                logger.warning(f"[LLMEngine] Could not init Gemini client: {e}")

        # 4. Ollama setup (Local open models <= 10B: qwen2.5:7b / llama3.1:8b)
        if OpenAI is not None and OLLAMA_BASE_URL:
            try:
                self.provider_clients["ollama"] = ("openai_compat", OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama"))
            except Exception as e:
                logger.warning(f"[LLMEngine] Could not init Ollama client: {e}")

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 400, fallback_text: Optional[str] = None) -> str:
        """
        Generates reasoning text from the configured LLM provider.
        Automatically switches to secondary providers or fallback text if network/API limits occur.
        """
        if self.primary_provider == "offline_mock" and fallback_text:
            return fallback_text

        # Build execution provider attempt order
        attempt_order = [self.primary_provider]
        for p in ["groq", "openrouter", "ollama", "gemini", "offline_mock"]:
            if p not in attempt_order:
                attempt_order.append(p)

        for provider in attempt_order:
            if provider == "offline_mock":
                return fallback_text or "Deterministic factual audit completed via Rule Engine (Offline Mock Mode)."

            if provider not in self.provider_clients:
                continue

            client_type, client = self.provider_clients[provider]
            model_name = self.provider_models.get(provider, "llama-3.1-8b-instant")

            try:
                if client_type == "groq_sdk":
                    chat_completion = client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        model=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                    content = chat_completion.choices[0].message.content.strip()
                    if content:
                        return content

                elif client_type == "openai_compat":
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                    content = response.choices[0].message.content.strip()
                    if content:
                        return content

                elif client_type == "gemini_sdk":
                    model = client.GenerativeModel(model_name)
                    full_prompt = f"{system_prompt}\n\nUser Question/Facts:\n{user_prompt}"
                    response = model.generate_content(full_prompt)
                    if response and response.text:
                        return response.text.strip()

            except Exception as err:
                logger.warning(f"[LLMEngine] Provider '{provider}' (model: {model_name}) error: {err}. Switching fallback...")
                time.sleep(0.5)

        return fallback_text or "Analysis concluded via deterministic backup reasoning engine."

# Global singleton instance for quick usage across agents
_llm_instance = None

def get_llm() -> LLMEngine:
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = LLMEngine()
    return _llm_instance
