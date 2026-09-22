"""Compatibility import for older Atlas code; new modules use app.ai_gateway."""
from app.ai_gateway import ALLOWED_MODELS, connection, model_options

__all__ = ['ALLOWED_MODELS', 'connection', 'model_options']
