"""Every command string the adapter sends, with where it comes from.

These copy simworld/simworld/communicator/unrealcv.py rather than calling it, because several
of its methods are unsafe in sync mode (see SIMWORLD.md, "Why the adapter bypasses unrealcv.py").
test_simworld_contract.py runs the real class against the fake server and checks both agree.

Line numbers are in unrealcv.py unless another file is named. `api.py` means the pip package
unrealcv 1.3.2, unrealcv/api.py.
"""

# Setup and lifecycle
def set_resolution(w, h): return f'vrun setres {w}x{h}w'  # :64
def async_skinned_assets(): return 'vrun Editor.AsyncSkinnedAssetCompilation 2'  # :66, "to correctly load the character"
def set_level(map_path): return f'vset /action/game/level {map_path}'  # api.py:1338, not in unrealcv.py
def clean_garbage(): return 'vset /action/clean_garbage'  # :102
def list_objects(): return 'vget /objects'  # :252
def list_cameras(): return 'vget /cameras'  # :890
def is_paused(): return 'vget /action/game/is_paused'  # api.py:1384, not in unrealcv.py


# Spawning. Order from communicator.py:603-645.
def spawn(asset, name): return f'vset /objects/spawn_bp_asset {asset} {name}'  # :95
def set_location(name, x, y, z): return f'vset /object/{name}/location {x} {y} {z}'  # :112
def set_rotation(name, pitch, yaw, roll): return f'vset /object/{name}/rotation {pitch} {yaw} {roll}'  # :124
def set_scale(name, x, y, z): return f'vset /object/{name}/scale {x} {y} {z}'  # :136
def set_collision(name, on): return f'vset /object/{name}/collision {on}'  # :181
def set_movable(name, on): return f'vset /object/{name}/object_mobility {on}'  # :192
def destroy(name): return f'vset /object/{name}/destroy'  # :241
def rename(name, new_name): return f'vset /object/{name}/name {new_name}'  # :263
def update_manager(manager): return f'vbp {manager} UpdateObjects'  # :512


# Stepping. The misspelling "intervel" is the real command.
def set_tick_interval(seconds): return f'vset /action/tick_intervel {seconds}'  # :225
def pause(): return 'vset /action/game/pause'  # :216
def resume(): return 'vset /action/game/resume'  # :219
def tick(): return 'vset /action/tick'  # :231


# Reading actors
def get_location(name): return f'vget /object/{name}/location'  # :290
def get_rotation(name): return f'vget /object/{name}/rotation'  # :321
def get_collisions(name): return f'vbp {name} GetCollisionNum'  # :278
def get_mask_color(name): return f'vget /object/{name}/color'  # api.py:744, not in unrealcv.py
def set_mask_color(name, r, g, b): return f'vset /object/{name}/color {r} {g} {b}'  # :148


# Humanoid agent
def move_forward(name): return f'vbp {name} MoveForward'  # :615


def turn(name, angle, direction):
    """Left sends a negated angle and clockwise=-1, as in :627-632. The leading 1 is seconds."""
    if direction == 'right':
        return f'vbp {name} TurnAround {1} {angle} {1}'
    return f'vbp {name} TurnAround {1} {-angle} {-1}'


def stop_agent(name): return f'vbp {name} StopAgent'  # :643
def step_forward(name, seconds, direction): return f'vbp {name} StepForward {seconds} {direction}'  # :655
def set_speed(name, speed): return f'vbp {name} SetMaxSpeed {speed}'  # :667
def sit_down(name): return f'vbp {name} SitDown'  # :677
def stand_up(name): return f'vbp {name} StandUp'  # :692
def get_on_scooter(name): return f'vbp {name} GetOnScooter'  # :707
def get_off_scooter(scooter): return f'vbp {scooter} GetOffScooter'  # :718, sent to the scooter, not the humanoid
def pick_up(name, target): return f'vbp {name} PickUp {target}'  # :729
def drop_object(name): return f'vbp {name} DropOff'  # :744
def enter_vehicle(name, vehicle): return f'vbp {name} EnterVehicle {vehicle}'  # :760
def exit_vehicle(name, vehicle): return f'vbp {name} ExitVehicle {vehicle}'  # :776
def discuss(name, variant): return f'vbp {name} Discussion {variant}'  # :792
def argue(name, variant): return f'vbp {name} Arguing {variant}'  # :803
def listen(name): return f'vbp {name} Listening'  # :813
def wave(name): return f'vbp {name} Wave2Dog'  # :823
def direct(name): return f'vbp {name} Directing'  # :833
def stop_gesture(name): return f'vbp {name} StopAction'  # :843
def drive(name, throttle, brake, steering): return f'vbp {name} SetState {throttle} {brake} {steering}'  # :856, :355


# Pedestrian NPCs
def npc_forward(name): return f'vbp {name} MoveForward'  # :407
def npc_stop(name): return f'vbp {name} StopPedestrian'  # :397
def npc_speed(name, speed): return f'vbp {name} SetMaxSpeed {speed}'  # :435


def npc_turn(name, angle, direction):
    """Same sign rule as turn, but a different blueprint function. See :419-424."""
    if direction == 'right':
        return f'vbp {name} Rotate_Angle {1} {angle} {1}'
    return f'vbp {name} Rotate_Angle {1} {-angle} {-1}'


# Camera
def get_camera_location(cam): return f'vget /camera/{cam}/location'  # :910
def get_camera_rotation(cam): return f'vget /camera/{cam}/rotation'  # :923
def get_camera_fov(cam): return f'vget /camera/{cam}/fov'  # :936
def get_camera_size(cam): return f'vget /camera/{cam}/size'  # :949
def set_camera_rotation(cam, pitch, yaw, roll): return f'vset /camera/{cam}/rotation {pitch} {yaw} {roll}'  # :971
def set_camera_fov(cam, fov): return f'vset /camera/{cam}/fov {fov}'  # :982
def set_camera_size(cam, w, h): return f'vset /camera/{cam}/size {w} {h}'  # :993
def render(cam, viewmode, fmt): return f'vget /camera/{cam}/{viewmode} {fmt}'  # :1050 and :1055


# Weather manager
def set_sun_direction(mgr, pitch, yaw): return f'vbp {mgr} SetSunDirection {pitch} {yaw}'  # :1190
def get_sun_direction(mgr): return f'vbp {mgr} GetSunDirection'  # :1203
def set_sun_intensity(mgr, value): return f'vbp {mgr} SetSunIntensity {value}'  # :1214
def get_sun_intensity(mgr): return f'vbp {mgr} GetSunIntensity'  # :1227
def set_fog(mgr, density, distance, falloff): return f'vbp {mgr} SetFog {density} {distance} {falloff}'  # :1240
def get_fog(mgr): return f'vbp {mgr} GetFog'  # :1253
def set_atmosphere(mgr, rayleigh, mie): return f'vbp {mgr} SetAtmosphere {rayleigh} {mie}'  # :1265
def get_atmosphere(mgr): return f'vbp {mgr} GetAtmosphere'  # :1278
