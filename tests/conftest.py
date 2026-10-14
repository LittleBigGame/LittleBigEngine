"""Test baseline kernel behavior without console trace noise."""

import pytest

from LBE.logger import ERROR, logger


@pytest.fixture(autouse=True)
def quiet_kernel_logger():
    previous_level = logger.min_level
    previous_pretty = logger.auto_pretty_print
    try:
        logger.set_min_level(ERROR)
        logger.auto_pretty_print = False
        yield
    finally:
        logger.records.clear()
        logger.set_min_level(previous_level)
        logger.auto_pretty_print = previous_pretty
