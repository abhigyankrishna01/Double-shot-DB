from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a versioned system prompt by name (without .txt extension)."""
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()
