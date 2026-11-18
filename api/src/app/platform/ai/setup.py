"""Create graph constraints and vector indexes as an explicit release action."""

import asyncio

from app.core.config import Settings
from app.core.logging import configure_logging
from app.platform.ai.runtime import ai_resources


async def setup(settings: Settings) -> None:
    async with ai_resources(settings.ai) as resources:
        await resources.knowledge.setup()
        await resources.vectors.setup()


def main() -> None:
    settings = Settings()
    configure_logging(settings.runtime.log_level)
    asyncio.run(setup(settings))


if __name__ == "__main__":
    main()
