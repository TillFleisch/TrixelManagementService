"""Common methods which can be used by different privatizers."""

from privatizer.blank_privatizer import BlankPrivatizer
from privatizer.combined_privatizers import (
    AveragePrivatizer,
    KalmanPrivatizer,
    SmoothingAveragePrivatizer,
)
from privatizer.config_schema import AvailablePrivatizers
from privatizer.latest_privatizer import LatestPrivatizer
from privatizer.naive_average_privatizer import (
    NaiveAveragePrivatizer,
    NaiveSmoothingAveragePrivatizer,
)
from privatizer.naive_kalman_privatizer import NaiveKalmanPrivatizer
from privatizer.privatizer import Privatizer

privatizer_lookup: dict[AvailablePrivatizers, type[Privatizer]] = {
    "blank": BlankPrivatizer,
    "latest": LatestPrivatizer,
    "naive_average": NaiveAveragePrivatizer,
    "naive_smoothing_average": NaiveSmoothingAveragePrivatizer,
    "average": AveragePrivatizer,
    "smoothing_average": SmoothingAveragePrivatizer,
    "naive_kalman": NaiveKalmanPrivatizer,
    "kalman": KalmanPrivatizer,
}


def get_privatizer(config_str: AvailablePrivatizers) -> type[Privatizer]:
    """Get the privatizer class based on the provided configuration literal."""
    return privatizer_lookup.get(config_str)
