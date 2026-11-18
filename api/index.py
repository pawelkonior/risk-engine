"""Native Vercel entrypoint; application imports perform no database I/O."""

from app.main import app

__all__ = ["app"]
