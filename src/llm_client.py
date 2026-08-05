"""Thin OpenAI wrapper shared by every agent.

Model is declared here explicitly (README section 9 requires the model name
to live in source code, not in .env): gpt-4o-mini, an OpenAI small model used
under the <=10B-parameter-class budget for this lab.
"""

from __future__ import annotations

import functools
import os
from typing import TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_random_exponential

load_dotenv()

MODEL_NAME = "gpt-4o-mini"

T = TypeVar("T", bound=BaseModel)


@functools.lru_cache(maxsize=1)
def get_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    return OpenAI(api_key=api_key)


@retry(stop=stop_after_attempt(4), wait=wait_random_exponential(min=1, max=20))
def structured_call(
    *,
    system_prompt: str,
    user_prompt: str,
    response_model: type[T],
    temperature: float = 0.0,
) -> T:
    """Calls MODEL_NAME and parses the reply into response_model."""
    client = get_client()
    completion = client.chat.completions.parse(
        model=MODEL_NAME,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=response_model,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("model refused or returned no parsed content")
    return parsed
