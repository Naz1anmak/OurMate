"""Обобщённый реестр тулов и цикл выполнения tool use."""
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMReply:
    content: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    reasoning_content: Optional[str] = None


@dataclass
class ToolSpec:
    schema: dict
    func: Callable[..., Awaitable[dict]]
    gate: Optional[str] = None


@dataclass
class ToolLoopResult:
    text: Optional[str] = None
    deferred_messages: list[str] = field(default_factory=list)
    denial: Optional[str] = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, spec: ToolSpec) -> None:
        self._tools[name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [spec.schema for spec in self._tools.values()]
