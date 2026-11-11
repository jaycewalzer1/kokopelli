"""A walking person's head, for the agent camera: looking around, step bob, and the eyes holding steady on what they look at.

Each frame `Head.update(agent_xyz, body_yaw)` returns the camera's world position and rotation. Units are Unreal's: cm, degrees,
yaw 0 = +X (east), 90 = +Y (south), positive pitch looks up.

- Step bob traces a sideways figure-8: down once per step, side to side once per stride (two steps). Its phase advances with
  distance walked, not time, so standing still means no bob and it speeds up and slows down with the walk.
- The dip is sharp at heel strike and the rise soft (|sin| has its corners at the bottom), and left steps are a little deeper.
- Amplitudes are about a third of a real head's, as games do. At full size it reads as shaky.
- Stabilizing: the camera moves with the bob but re-aims at a point 10 m along the gaze, the way eyes counter-rotate. That is
  most of what makes it feel like a head rather than a handheld camera.
- Every offset goes through a critically damped spring, so turns ease in and out and starting to walk ramps up.
- A little slow noise when nothing else moves: breathing and sway.
"""
import math
from dataclasses import dataclass, field

EYE_UP_CM, EYE_FORWARD_CM = 70.0, 12.0   # where SimWorld puts the agent camera, measured on the packaged server
STEP_LENGTH_CM = 84.0                    # 1.9 steps/s at 1.6 m/s
REF_SPEED_CM_S = 160.0
BOB_DOWN_CM, BOB_SIDE_CM = 1.8, 1.4
ROLL_DEG, BOB_PITCH_DEG = 0.6, 0.2
LEFT_DEEPER = 0.08
FOCUS_CM = 1000.0

# Where the person looks, relative to the way they walk: (from second, yaw degrees right, pitch degrees up). Each glance is held
# until the next; the gaze spring makes the turns. Written for test_clip's path: planters on the right, lawn on the left,
# the terraced building ahead.
GLANCES = [(0.0, 0, -6), (1.5, 36, -15), (3.3, 6, -3), (4.5, -32, -2), (6.0, 8, 9), (7.5, 18, -6), (8.8, 0, -4)]


def spring(value, velocity, target, stiffness, dt, substeps=8):
    """One frame of a critically damped spring (damping 2*sqrt(k)), in small steps so it stays stable at 30 fps."""
    damping = 2 * math.sqrt(stiffness)
    h = dt / substeps
    for _ in range(substeps):
        velocity += (stiffness * (target - value) - damping * velocity) * h
        value += velocity * h
    return value, velocity


def drift(t, seed):
    """Smooth noise around 0.2-0.3 Hz in [-1, 1]: three sines at unrelated rates, so it never visibly repeats in a clip."""
    return (math.sin(2 * math.pi * 0.23 * t + seed) + 0.6 * math.sin(2 * math.pi * 0.31 * t + 2.1 * seed)
            + 0.3 * math.sin(2 * math.pi * 0.17 * t + 3.7 * seed)) / 1.9


@dataclass
class Spring:
    stiffness: float
    value: float = 0.0
    velocity: float = 0.0

    def to(self, target, dt):
        self.value, self.velocity = spring(self.value, self.velocity, target, self.stiffness, dt)
        return self.value


@dataclass
class Head:
    dt: float
    glances: list = field(default_factory=lambda: list(GLANCES))
    t: float = 0.0
    phase: float = 0.0
    last: tuple = None

    def __post_init__(self):
        self.yaw, self.pitch = Spring(60.0), Spring(60.0)          # head turns settle in about half a second
        self.side, self.down, self.roll = Spring(120.0), Spring(120.0), Spring(90.0)
        self.yaw.value, self.pitch.value = self.glances[0][1], self.glances[0][2]

    def glance(self):
        return next((yaw, pitch) for start, yaw, pitch in reversed(self.glances) if self.t >= start)

    def update(self, agent, body_yaw):
        """agent is the body's (x, y, z) now; returns ((x, y, z), (pitch, yaw, roll)) for the camera, and what went into it."""
        moved = math.dist(agent[:2], self.last[:2]) if self.last else 0.0
        self.last = agent
        speed = moved / self.dt
        self.phase += moved / STEP_LENGTH_CM * math.pi              # pi per step
        amp = min(speed / REF_SPEED_CM_S, 1.5)

        stride = math.sin(self.phase / 2)                           # one cycle per two steps: left, then right
        deeper = 1 + LEFT_DEEPER * (1 if stride > 0 else -1)
        down = BOB_DOWN_CM * amp * deeper * (abs(math.sin(self.phase)) - 2 / math.pi)  # lowest, with a sharp corner, at heel strike
        side = BOB_SIDE_CM * amp * stride
        roll = ROLL_DEG * amp * stride
        breathe = 0.3 * drift(self.t, 1.0)                          # cm
        sway = 0.15 * drift(self.t, 4.0)                            # degrees

        gaze_yaw, gaze_pitch = self.glance()
        head_yaw = self.yaw.to(gaze_yaw, self.dt)
        head_pitch = self.pitch.to(gaze_pitch, self.dt)
        side = self.side.to(side, self.dt)
        down = self.down.to(down + breathe, self.dt)
        roll = self.roll.to(roll, self.dt)

        body = math.radians(body_yaw)
        forward, right = (math.cos(body), math.sin(body)), (-math.sin(body), math.cos(body))
        eye = (agent[0] + EYE_FORWARD_CM * forward[0], agent[1] + EYE_FORWARD_CM * forward[1], agent[2] + EYE_UP_CM)
        # The point the eyes hold, from the unbobbed eye along the gaze.
        look_yaw, look_pitch = math.radians(body_yaw + head_yaw), math.radians(head_pitch + sway)
        focus = (eye[0] + FOCUS_CM * math.cos(look_pitch) * math.cos(look_yaw),
                 eye[1] + FOCUS_CM * math.cos(look_pitch) * math.sin(look_yaw),
                 eye[2] + FOCUS_CM * math.sin(look_pitch))
        camera = (eye[0] + side * right[0], eye[1] + side * right[1], eye[2] + down)
        dx, dy, dz = (f - c for f, c in zip(focus, camera, strict=False))
        yaw = math.degrees(math.atan2(dy, dx))
        pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy))) + BOB_PITCH_DEG * amp * math.sin(2 * self.phase)
        self.t += self.dt
        return camera, (pitch, yaw, roll), {"speed_cm_s": round(speed, 1), "phase": round(self.phase, 3), "side_cm": round(side, 2),
                                            "down_cm": round(down, 2), "head_yaw": round(head_yaw, 2), "head_pitch": round(head_pitch, 2),
                                            "roll": round(roll, 3)}
