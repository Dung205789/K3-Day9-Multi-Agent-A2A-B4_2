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
        raw_translating_model = (os.getenv("TRANSLATING_MODEL") or "riva-translate-4b-instruct-v2").strip()
        if "nvidia.com" in self.base_url and "/" not in raw_translating_model:
            self.translating_model = f"nvidia/{raw_translating_model}".lower()
        else:
            self.translating_model = raw_translating_model.lower()
        self.client = None
        if self.api_key:
            try:
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except Exception as e:
                print(f"Warning: Failed to initialize OpenAI client: {e}")

    def translate_to_english(self, text: str) -> str:
        if not self.client or not text:
            return text
        try:
            response = self.client.chat.completions.create(
                model=self.translating_model,
                messages=[
                    {"role": "system", "content": "You are a professional translator. Translate the given text into English accurately. Output ONLY the translated English text without any intro or commentary."},
                    {"role": "user", "content": text}
                ],
                temperature=0.0,
                max_tokens=300
            )
            translated = response.choices[0].message.content.strip()
            return translated if translated else text
        except Exception as e:
            print(f"Translation failed with model {self.translating_model}: {e}")
            return text

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
