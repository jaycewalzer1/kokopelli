"""Pure formulas: camera geometry, the sun, headings and hearing. No network, easy to test."""
import math
from typing import Optional

from kokopelli.loop.physics import Intrinsics, Rotation, TimeOfDay, Vec3


def intrinsics_from_fov(width: int, height: int, fov_horizontal_deg: float) -> Intrinsics:
    """Pinhole intrinsics from the horizontal field of view.

    Half the image width subtends half the fov, so tan(fov/2) = (width/2) / fx,
    which gives fx = (width/2) / tan(fov/2). Unreal renders square pixels, so fy = fx.
    The principal point (where the optical axis lands) is assumed to be the image centre.
    """
    if not 0 < fov_horizontal_deg < 180:
        raise ValueError(f"fov must be in (0, 180), got {fov_horizontal_deg}")
    fx = (width / 2) / math.tan(math.radians(fov_horizontal_deg) / 2)
    return Intrinsics(width=width, height=height, fov_horizontal_deg=fov_horizontal_deg,
                      fx=fx, fy=fx, cx=width / 2, cy=height / 2)


def camera_to_world(rotation: Rotation) -> list[list[float]]:
    """3x3 matrix whose columns are the camera's forward, right and up axes in world space.

    Same formula as Unreal's FRotationMatrix. Unreal is left-handed, so the determinant is -1
    when this is read as a right-handed matrix. Do not feed it to OpenCV without converting.
    """
    p, y, r = (math.radians(a) for a in (rotation.pitch, rotation.yaw, rotation.roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    forward = [cp * cy, cp * sy, sp]
    right = [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp]
    up = [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp]
    return [[forward[i], right[i], up[i]] for i in range(3)]


def project_point(point: Vec3, location: Vec3, rotation: Rotation, k: Intrinsics) -> Optional[tuple[float, float]]:
    """World point to pixel (u right, v down). None if it is behind the camera."""
    d = (point.x - location.x, point.y - location.y, point.z - location.z)
    m = camera_to_world(rotation)
    forward, right, up = (sum(m[i][axis] * d[i] for i in range(3)) for axis in range(3))
    if forward <= 0:
        return None
    return k.cx + k.fx * right / forward, k.cy - k.fy * up / forward


def heading_to(origin: Vec3, target: Vec3) -> tuple[float, float]:
    """Yaw and pitch that point from origin at target. Yaw matches local_planner.py:181."""
    dx, dy, dz = target.x - origin.x, target.y - origin.y, target.z - origin.z
    return math.degrees(math.atan2(dy, dx)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def angle_delta(target_deg: float, current_deg: float) -> float:
    """Shortest signed turn in [-180, 180). Positive means turn right, since yaw grows clockwise."""
    return (target_deg - current_deg + 180) % 360 - 180


def distance_cm(a: Vec3, b: Vec3) -> float:
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def distance_2d_cm(a: Vec3, b: Vec3) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def hearing(speaker: Vec3, listeners: dict[str, Vec3], radius_cm: float) -> list[str]:
    """Ids within radius_cm of the speaker, in 3D, sorted. A listener exactly on the radius hears."""
    return sorted(i for i, where in listeners.items() if distance_cm(speaker, where) <= radius_cm)


def parse_clock(hhmm: str) -> float:
    """'08:30' or '08:30:15' to seconds since midnight."""
    parts = [int(p) for p in hhmm.split(":")]
    if len(parts) == 2:
        parts.append(0)
    if len(parts) != 3 or not (0 <= parts[0] < 24 and 0 <= parts[1] < 60 and 0 <= parts[2] < 60):
        raise ValueError(f"expected HH:MM or HH:MM:SS, got {hhmm!r}")
    return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]


def format_clock(seconds: float) -> str:
    whole = int(seconds) % 86400
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def time_of_day(sim_time_s: float, start_s: float, sunrise_h: float = 6.0, sunset_h: float = 18.0,
                max_elevation_deg: float = 70.0, sunrise_azimuth_deg: float = 90.0,
                max_intensity: float = 10.0) -> TimeOfDay:
    """Map sim time to the sun with a deliberately simple model.

    Let f = (hour - sunrise) / (sunset - sunrise), which runs 0 to 1 across the day.
      elevation = max_elevation * sin(pi * f)     above the horizon by day, below it at night
      azimuth   = sunrise_azimuth + 180 * f       sweeps a half circle across the day
      intensity = max_intensity * max(0, sin(pi * f))     zero at night

    At night f leaves 0..1, so we wrap it to keep the sun moving steadily under the horizon.
    Latitude, season and twilight are ignored. It only has to be consistent, not astronomical.
    """
    seconds = (start_s + sim_time_s) % 86400
    hour = seconds / 3600
    day_length = sunset_h - sunrise_h
    if not 0 < day_length < 24:
        raise ValueError("sunset must be after sunrise on the same day")
    if hour >= sunrise_h and hour <= sunset_h:
        f = (hour - sunrise_h) / day_length
        wave = math.sin(math.pi * f)
    else:
        night_length = 24 - day_length
        into_night = (hour - sunset_h) % 24
        f = 1 + into_night / night_length  # runs 1 to 2 overnight
        wave = -math.sin(math.pi * (into_night / night_length))
    return TimeOfDay(seconds_since_midnight=seconds, clock=format_clock(seconds),
                     sun_elevation_deg=max_elevation_deg * wave,
                     sun_azimuth_deg=(sunrise_azimuth_deg + 180 * f) % 360,
                     sun_intensity=max_intensity * max(0.0, wave))


def sun_pitch_from_elevation(elevation_deg: float, sign: int = -1) -> float:
    """Weather-manager pitch for a sun elevation, kept inside its -89..89 limit (unrealcv.py:1187).

    sign is -1 because a light shining down has negative pitch in Unreal, and the only real
    reply in the code is P=-26 (communicator.py:967). The commented-out presets in
    weather_manager.py:272,304 imply the opposite, so the gate script tests this.
    """
    return max(-89.0, min(89.0, sign * elevation_deg))
