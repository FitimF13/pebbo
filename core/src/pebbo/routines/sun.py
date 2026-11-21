"""Sunrise and sunset, computed locally from the configured location.

Uses the approximation of the NOAA solar calculator, accurate to a few minutes, which is
enough for routines. No weather or location service is contacted: the owner enters the
location once with ``PEBBO_LATITUDE`` and ``PEBBO_LONGITUDE``.
"""

from __future__ import annotations

import math
import os
from datetime import UTC, date, datetime, timedelta, tzinfo

# The sun's apparent radius and atmospheric refraction, in degrees below the horizon.
_ZENITH = math.radians(90.833)


def location() -> tuple[float, float] | None:
    try:
        return float(os.environ["PEBBO_LATITUDE"]), float(os.environ["PEBBO_LONGITUDE"])
    except (KeyError, ValueError):
        return None


def sun_times(
    day: date, latitude: float, longitude: float, zone: tzinfo
) -> tuple[datetime | None, datetime | None]:
    """Sunrise and sunset on a day in local time. ``None`` during polar day or night."""
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    equation_of_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    lat = math.radians(latitude)
    cos_hour_angle = math.cos(_ZENITH) / (math.cos(lat) * math.cos(declination)) - math.tan(lat) * math.tan(
        declination
    )
    if not -1 <= cos_hour_angle <= 1:
        return None, None
    hour_angle = math.degrees(math.acos(cos_hour_angle))
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)

    def at(minutes: float) -> datetime:
        return (midnight + timedelta(minutes=minutes)).astimezone(zone)

    return (
        at(720 - 4 * (longitude + hour_angle) - equation_of_time),
        at(720 - 4 * (longitude - hour_angle) - equation_of_time),
    )
