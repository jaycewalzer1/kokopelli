"""Weather, clock and sun for SimWorldPhysics, as a mixin. Split out of simworld.py."""
import json
import re
from typing import Optional

from runtime.adapters import simworld_commands as c
from runtime.adapters.simworld_config import WEATHER_ACTOR
from runtime.adapters.simworld_math import parse_clock, sun_pitch_from_elevation, time_of_day
from runtime.adapters.simworld_wire import CommandError, SimWorldError
from runtime.physics import TimeOfDay, Weather


class WeatherMixin:
    """Needs self.config, self.wire, self.weather_available, self.start_s, self.sun_max, self.fog,
    self.atmosphere, self.initial_weather, self.warnings and self.sim_time_s from SimWorldPhysics."""

    def _apply_weather_settings(self) -> None:
        if not self.weather_available:
            return
        # Only recorded. Using it as the maximum would feed our own last value back in on the
        # next run against the same server, and the world would get darker each time.
        self.initial_weather = self.read_weather()
        if self.fog:
            self.wire.request(c.set_fog(WEATHER_ACTOR, *self.fog), resend=False)
        if self.atmosphere:
            self.wire.request(c.set_atmosphere(WEATHER_ACTOR, *self.atmosphere), resend=False)

    def set_weather(self, fog: Optional[tuple[float, float, float]] = None,
                    atmosphere: Optional[tuple[float, float]] = None) -> Weather:
        """Set fog (density, distance_cm, falloff) and/or atmosphere (rayleigh, mie). Returns a read-back."""
        if not self.weather_available:
            raise SimWorldError("no weather manager in this world")
        if fog is not None:
            density, distance, falloff = fog
            if not (0 <= density <= 100 and 0 <= distance <= 5000 and 0 <= falloff <= 2):  # unrealcv.py:1236-1238
                raise ValueError(f"fog out of range: {fog}. Limits are 0-100, 0-5000, 0-2.")
            self.fog = (density, distance, falloff)
            self.wire.request(c.set_fog(WEATHER_ACTOR, *self.fog), resend=False)
        if atmosphere is not None:
            rayleigh, mie = atmosphere
            if not (0 <= rayleigh <= 2 and 0 <= mie <= 5):  # unrealcv.py:1262-1263
                raise ValueError(f"atmosphere out of range: {atmosphere}. Limits are 0-2, 0-5.")
            self.atmosphere = (rayleigh, mie)
            self.wire.request(c.set_atmosphere(WEATHER_ACTOR, *self.atmosphere), resend=False)
        return self.read_weather()

    def set_clock(self, clock: str) -> TimeOfDay:
        """Jump the time of day. Sim time keeps counting, only the clock it maps to changes."""
        self.start_s = (parse_clock(clock) - self.sim_time_s) % 86400
        self._apply_sun(self.sim_time_s)
        return self._time_of_day(self.sim_time_s)

    def _time_of_day(self, sim_time_s: float) -> TimeOfDay:
        cfg = self.config
        return time_of_day(sim_time_s, self.start_s, cfg.sunrise_h, cfg.sunset_h, cfg.max_sun_elevation_deg,
                           cfg.sunrise_azimuth_deg, self.sun_max)

    def _apply_sun(self, sim_time_s: float) -> None:
        if not self.weather_available:
            return
        tod = self._time_of_day(sim_time_s)
        pitch = sun_pitch_from_elevation(tod.sun_elevation_deg, self.config.sun_pitch_sign)
        self.wire.request(c.set_sun_direction(WEATHER_ACTOR, round(pitch, 4), round(tod.sun_azimuth_deg, 4)), resend=False)
        self.wire.request(c.set_sun_intensity(WEATHER_ACTOR, round(tod.sun_intensity, 4)), resend=False)

    def _weather_json(self, command: str) -> dict:
        """Weather replies are JSON padded with tabs and newlines (communicator.py:958-963)."""
        text = self.wire.request(command, resend=True)
        cleaned = re.sub(r"\s+", " ", re.sub(r"[\r\n\t]", "", str(text))).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise CommandError(f"{command!r} replied with something that is not JSON: {text!r}") from e

    def read_weather(self) -> Weather:
        if not self.weather_available:
            return Weather(available=False)
        try:
            rotation = self._weather_json(c.get_sun_direction(WEATHER_ACTOR)).get("rotation", "")
            pitch = re.search(r"P=([-\d.]+)", rotation)
            yaw = re.search(r"Y=([-\d.]+)", rotation)
            fog = self._weather_json(c.get_fog(WEATHER_ACTOR))
            atmosphere = self._weather_json(c.get_atmosphere(WEATHER_ACTOR))
            intensity = self._weather_json(c.get_sun_intensity(WEATHER_ACTOR))
            return Weather(available=True,  # key names from communicator.py:966-1088
                           sun_pitch_deg=float(pitch.group(1)) if pitch else None,
                           sun_yaw_deg=float(yaw.group(1)) if yaw else None,
                           sun_intensity=float(intensity["SunIntensity"]) if "SunIntensity" in intensity else None,
                           fog_density=float(fog["FogDensity"]) if "FogDensity" in fog else None,
                           fog_distance_cm=float(fog["FogDistance"]) if "FogDistance" in fog else None,
                           fog_falloff=float(fog["FogFalloff"]) if "FogFalloff" in fog else None,
                           rayleigh=float(atmosphere["Rayleigh Scattering Scale"]) if "Rayleigh Scattering Scale" in atmosphere else None,
                           mie=float(atmosphere["Mie Scattering Scale"]) if "Mie Scattering Scale" in atmosphere else None)
        except (CommandError, ValueError) as e:
            self.warnings.append(f"could not read weather: {e}")
            return Weather(available=False)
