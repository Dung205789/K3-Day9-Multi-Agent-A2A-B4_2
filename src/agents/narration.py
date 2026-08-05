from pydantic import BaseModel


class Narration(BaseModel):
    summary: str
