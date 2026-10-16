"""Convenience ASGI entry point; the application lives in backend.main."""

from backend.main import app

__all__ = ["app"]