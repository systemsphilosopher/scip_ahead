"""Shared diagnostic logger for SCIP Ahead.

Writes to `scip_ahead_log.txt` in the current working directory — the same
location as `scip_ahead.db` — so the log sits next to the database it describes.

Import the configured `logger` from this module in any other module:

    from scip_ahead.scip_ahead_logger import logger
    logger.info("...")
"""
import logging

# Co-located with scip_ahead.db (both are relative to the working directory).
LOG_PATH = "scip_ahead_log.txt"

logger = logging.getLogger("scip_ahead")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    _handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_handler)
    logger.propagate = False
