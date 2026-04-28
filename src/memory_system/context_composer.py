from __future__ import annotations

from memory_system.schemas import ContextBlock, MemoryItemRead


def compose_context(
    task: str,
    memories: list[MemoryItemRead],
    *,
    token_budget: int = 2000,
) -> ContextBlock:
    if token_budget < 1:
        raise ValueError("token_budget must be greater than zero")

    warnings: list[str] = []
    memory_ids: list[str] = []
    blocks: list[str] = []
    remaining = token_budget

    header = f"Relevant memory for task: {task.strip() or 'unspecified'}"
    blocks.append(header)
    remaining -= len(header)

    for memory in memories:
        if memory.status != "active":
            warnings.append(f"Skipped {memory.id}: status={memory.status}")
            continue

        if memory.confidence != "confirmed":
            warnings.append(f"{memory.id}: confidence={memory.confidence}")
        if memory.last_verified_at is None:
            warnings.append(f"{memory.id}: missing last_verified_at")

        source = ", ".join(memory.source_event_ids)
        block = (
            f"[{memory.confidence}][{memory.memory_type}][{memory.scope}]\n"
            f"Subject: {memory.subject}\n"
            f"Content: {memory.content}\n"
            f"Source: {source}"
        )
        block_size = len(block) + 2
        if block_size > remaining:
            warnings.append(f"Stopped before {memory.id}: token_budget exhausted")
            break

        blocks.append(block)
        memory_ids.append(memory.id)
        remaining -= block_size

    return ContextBlock(
        content="\n\n".join(blocks),
        memory_ids=memory_ids,
        warnings=warnings,
        metadata={"task": task, "token_budget": str(token_budget), "remaining": str(max(0, remaining))},
    )
