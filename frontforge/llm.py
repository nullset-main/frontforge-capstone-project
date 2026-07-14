from langchain_ollama import ChatOllama

DEFAULT_MODEL = "qwen2.5:3b"


def get_llm(
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    num_ctx: int = 8192,
) -> ChatOllama:
    """
    Returns a configured ChatOllama instance.

    temperature is kept low (0.2) for both agents since we want structured,
    consistent output (JSON plans / compilable JSX) rather than creative text.

    num_ctx is bumped above the Ollama default (2048) because plans + RAG
    context + component specs can get long. Lower this if your machine is
    RAM constrained.
    """
    return ChatOllama(
        model=model,
        temperature=temperature,
        num_ctx=num_ctx,
    )
