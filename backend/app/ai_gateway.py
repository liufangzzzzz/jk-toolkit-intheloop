"""Shared AI gateway configuration for every workbench feature."""
import os

# This is the single model allowlist for the whole application. A provider
# account may expose additional models; they remain unavailable until this
# reviewed list is changed in code.
ALLOWED_MODELS = (
    {'id': 'deepseek/deepseek-v4-flash-vision-exp', 'name': 'DeepSeek V4 Flash Vision'},
    {'id': 'anthropic/claude-4.8-opus', 'name': 'Claude 4.8 Opus'},
    {'id': 'anthropic/claude-opus-5', 'name': 'Claude Opus 5'},
    {'id': 'openai/gpt-5.6-terra', 'name': 'GPT-5.6 Terra'},
)


def connection():
    """Return the server-only Modelink connection shared by all modules."""
    key = os.environ.get('MODELINK_API_KEY', '').strip()
    base = (os.environ.get('MODELINK_BASE_URL', '').strip() or 'https://api.qnaigc.com/v1').rstrip('/')
    return key, base, 'Modelink'


async def model_options():
    """Expose approved models only after the server-side key is configured."""
    key, base, _ = connection()
    if not key or not base:
        return []
    return [dict(item) for item in ALLOWED_MODELS]
