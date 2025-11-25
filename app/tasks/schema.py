
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Task:
    task_id: str
    prompt: str
    sector: str
    priority: int = 1
    max_retries: int = 2
    provider_hint: Optional[str] = None
    tags: list = field(default_factory=list)
