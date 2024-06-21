"""Logging helper which provides a logger with custom formatting and user-defined log-level."""

import logging
import sys

import colorlog
from colorlog import ColoredFormatter

from schema import Config, TestConfig

__log_level = logging.NOTSET
if "pytest" in sys.modules:
    __log_level = TestConfig().log_level
else:
    __log_level = Config().log_level


formatter = ColoredFormatter(
    "%(asctime)s %(log_color)s%(levelname)s%(fg_white)s:%(name)s: %(log_color)s%(message)s",
    reset=True,
    style="%",
)


def get_logger(name: str | None):
    """
    Get a pre-configured logger.

    :param: name of the logger, if None the root logger is used
    :return: pre-configured logger
    """
    handler = colorlog.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(__log_level)
    return logger
