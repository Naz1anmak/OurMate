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
    called_tools: list[str] = field(default_factory=list)
    # Тул сам отправил готовое сообщение (карточка/подтверждение) — финальный текст LLM
    # не показываем, иначе дублируем ответ (см. флаг "_silent" в результате тула).
    suppress_text: bool = False
    # Краткая служебная пометка от тула ("_context_note") — её кладём в контекст диалога
    # вместо пустого ответа, когда финал подавлен, чтобы продолжения имели опору.
    context_note: Optional[str] = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, spec: ToolSpec) -> None:
        self._tools[name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [spec.schema for spec in self._tools.values()]

    def items(self):
        """Пары (имя, ToolSpec) — переносить тулы между реестрами без доступа к приватному полю."""
        return self._tools.items()


DEFAULT_DENIAL = "Эта команда доступна в основной беседе или в ЛС для пользователей из списка группы."


def _parse_args(raw: str) -> Optional[dict]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


async def run_tool_loop(
    messages: list,
    tool_context: dict,
    *,
    registry: ToolRegistry,
    llm_call: Callable[..., Awaitable[LLMReply]],
    max_tool_rounds: int = 1,
    on_tool_start: Optional[Callable[[str], Awaitable[None]]] = None,
) -> ToolLoopResult:
    """Гоняет tool use: вызов LLM → исполнение тулов → повторный вызов. Не знает про Telegram."""
    deferred: list[str] = []
    called: list[str] = []
    silent = False
    context_note: Optional[str] = None
    work = list(messages)
    rounds = 0

    while True:
        tools = registry.schemas() or None
        reply = await llm_call(work, tools)

        if not reply.tool_calls:
            return ToolLoopResult(text=reply.content or "", deferred_messages=deferred,
                                  called_tools=called, suppress_text=silent)

        # Гейт доступа: если любой запрошенный тул закрыт — короткое замыкание на заглушку.
        for tc in reply.tool_calls:
            spec = registry.get(tc["function"]["name"])
            if spec and spec.gate and not tool_context.get(spec.gate, False):
                denial = tool_context.get("denial_text") or DEFAULT_DENIAL
                return ToolLoopResult(text=None, deferred_messages=[], denial=denial)

        # Assistant-сообщение с tool_calls + reasoning_content (V4 round-trip, иначе 400).
        work.append({
            "role": "assistant",
            "content": reply.content or "",
            "reasoning_content": reply.reasoning_content,
            "tool_calls": reply.tool_calls,
        })

        for tc in reply.tool_calls:
            name = tc["function"]["name"]
            called.append(name)
            if on_tool_start is not None:
                try:
                    await on_tool_start(name)
                except Exception as exc:  # noqa: BLE001 — индикатор не критичен
                    logger.debug("on_tool_start упал: %s", exc)
            spec = registry.get(name)
            args = _parse_args(tc["function"]["arguments"])
            if spec is None:
                result = {"error": "unknown_tool"}
            elif args is None:
                result = {"error": "bad_arguments"}
            else:
                try:
                    result = await spec.func(tool_context=tool_context, **args)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Тул %s упал: %s", name, exc)
                    result = {"error": "tool_failed"}
            deferred.extend(result.pop("_deferred", []) or [])
            if result.pop("_silent", False):
                silent = True
            note = result.pop("_context_note", None)
            if note:
                context_note = note
            work.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False),
            })

        # Тул сам отправил готовое сообщение (карточка/подтверждение) — второй вызов LLM не нужен:
        # незачем генерить подтверждающую фразу, которую мы всё равно подавим (и которая успевает
        # мелькнуть в стриме/драфте). Завершаемся сразу.
        if silent:
            return ToolLoopResult(text="", deferred_messages=deferred,
                                  called_tools=called, suppress_text=True,
                                  context_note=context_note)

        rounds += 1
        if rounds > max_tool_rounds:
            reply = await llm_call(work, None)  # финал без тулов
            return ToolLoopResult(text=reply.content or "", deferred_messages=deferred,
                                  called_tools=called, suppress_text=silent)
