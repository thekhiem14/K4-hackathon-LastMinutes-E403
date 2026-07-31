"""Back-compat: pipeline still imports ai.gemini_client.GeminiClient."""

from ai.openrouter_client import GeminiClient, OpenRouterClient

__all__ = ["GeminiClient", "OpenRouterClient"]
