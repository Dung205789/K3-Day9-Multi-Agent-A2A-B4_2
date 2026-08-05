import os
from dotenv import load_dotenv
from openai import OpenAI
from typing import Optional

load_dotenv()

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
        self.model = os.getenv("OPENAI_MODEL", "meta/llama-3.1-8b-instruct")
        self.client = None
        if self.api_key:
            try:
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception as e:
                print(f"Warning: Failed to initialize OpenAI client: {e}")

    def evaluate_reasoning(self, prompt: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an AI assistant verifying e-commerce dispute resolution decisions according to Olist policies."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=300
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM API call skipped/failed: {e}")
            return None
