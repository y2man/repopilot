"""Bounded context construction that preserves source locations for citations."""

def build_context(sources: list[dict], max_tokens: int = 12000) -> str:
    # Conservative character estimate for mixed code/prose; the provider tokenizer is not local.
    budget = max_tokens * 4
    blocks=[]
    used=0
    for index, source in enumerate(sources, start=1):
        header=f"SOURCE {index}: {source['path']}:{source['start_line']}-{source['end_line']}\n"
        remaining=budget-used-len(header)
        if remaining <= 0: break
        content=str(source.get("content", ""))
        if len(content)>remaining:
            content=content[:remaining]
        blocks.append(header+content)
        used += len(header)+len(content)+2
        if used >= budget: break
    return "\n\n".join(blocks)
