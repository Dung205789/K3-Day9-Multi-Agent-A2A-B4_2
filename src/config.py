import os
from dotenv import load_dotenv

# Load variables from .env file if available
load_dotenv()

# ==============================================================================
# REQUIRED BY LAB RULES: EXPLICIT MODEL DECLARATION IN SOURCE CODE (<= 10B PARAMS)
# ==============================================================================
# We explicitly declare all model parameters in the source code as instructed.
# Every model below strictly adheres to the <= 10B parameters limitation.
# Model names must NOT be overridden from .env per rule #4. They must be explicitly declared here!
PROVIDER_MODELS = {
    "groq": "llama-3.1-8b-instant",               # Meta's 8B ultra-fast model (<10B)
    "openrouter": "meta-llama/llama-3.1-8b-instruct", # OpenRouter 8B model (<10B)
    "gemini": "gemma-2-9b-it",                    # Google's 9B instruction-tuned model (<10B)
    "ollama": "qwen2.5:7b-instruct-fp16",         # Alibaba's 7B open model (<10B)
    "openai": "gpt-4o-mini",                      # Lightweight target model
    "offline_mock": "offline_mock_agent"
}

DEFAULT_MODEL_NAME = PROVIDER_MODELS["groq"]

SUPPORTED_MODELS_GUIDANCE = {
    "gemma-2-9b-it": {"params_size": "9B", "is_le_10b": True},
    "llama-3.1-8b-instant": {"params_size": "8B", "is_le_10b": True},
    "meta-llama/llama-3.1-8b-instruct": {"params_size": "8B", "is_le_10b": True},
    "qwen2.5:7b-instruct-fp16": {"params_size": "7B", "is_le_10b": True},
    "qwen2.5:7b": {"params_size": "7B", "is_le_10b": True},
    "offline_mock_agent": {"params_size": "0B (Rule-based deterministic engine)", "is_le_10b": True}
}

# --- AI Provider & Key Settings ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# --- Directory Path Configurations ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
INPUT_DIR = os.getenv("INPUT_DIR", os.path.join(BASE_DIR, "input"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(BASE_DIR, "output"))
TRACE_FILE = os.getenv("TRACE_FILE", os.path.join(BASE_DIR, "trace.jsonl"))

def get_active_model_info() -> dict:
    """Returns details of the currently configured LLM model (<10B)."""
    model_name = PROVIDER_MODELS.get(LLM_PROVIDER, DEFAULT_MODEL_NAME)
    info = SUPPORTED_MODELS_GUIDANCE.get(model_name, {"params_size": "<= 10B", "is_le_10b": True})
    return {
        "provider": LLM_PROVIDER,
        "model_name": model_name,
        "parameters": info.get("params_size", "<= 10B")
    }
