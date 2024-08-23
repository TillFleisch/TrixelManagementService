"""This module contains different privatizers which are combinations of other privatizers."""

from typing import ClassVar

from config_schema import GlobalConfig
from privatizer.config_schema import (
    AveragePrivatizerConfig,
    SmoothingAveragePrivatizerConfig,
)
from privatizer.correlation_evaluating_privatizer import CorrelationEvaluatingPrivatizer
from privatizer.naive_average_privatizer import (
    NaiveAveragePrivatizer,
    NaiveSmoothingAveragePrivatizer,
)


class AveragePrivatizer(CorrelationEvaluatingPrivatizer, NaiveAveragePrivatizer):
    """
    The average privatizer extends on the naive average privatizer approach by implementing proper sensor evaluation.

    This privatizer generates higher quality results, since it does not include "bad" sensors.
    A sensor is only included when it is deemed 'reliable' and 'trustworthy'.
    The criteria which must be met by a sensors depend on the `CorrelationEvaluatingPrivatizer`.
    Furthermore, due to the use of the `CorrelationEvaluatingPrivatizer`, incoming sensor data is lightly filtered.
    """

    config: ClassVar[AveragePrivatizerConfig] = GlobalConfig.config.privatizer_config


class SmoothingAveragePrivatizer(CorrelationEvaluatingPrivatizer, NaiveSmoothingAveragePrivatizer):
    """Like AP, additionally applies exponential smoothing separately to local and subtrixel measurements."""

    config: ClassVar[SmoothingAveragePrivatizerConfig] = GlobalConfig.config.privatizer_config
