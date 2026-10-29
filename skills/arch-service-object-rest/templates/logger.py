"""logger — shared loguru instance for the test suite.

Import as ``from tests.utils.logger import logger``.
Configured once at module import; callers never re-configure.
"""
from __future__ import annotations

import os
import sys

from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format=(
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>"
    ),
    colorize=True,
    enqueue=False,
)

__all__ = ["logger"]
