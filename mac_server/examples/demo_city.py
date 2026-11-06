"""End-to-end check: build SimWorld's demo_city_1 on the Mac server with the unmodified client, then capture views.

    ~/Desktop/kokopelli/simworld/.venv/bin/python -I examples/demo_city.py [out_dir]
"""
import os
import sys
import time

import cv2

SIMWORLD = os.path.expanduser('~/Desktop/kokopelli/simworld')
sys.path.insert(0, SIMWORLD)
os.chdir(SIMWORLD)  # Config() resolves its default paths relative to the package

from simworld.communicator.communicator import Communicator  # noqa: E402
from simworld.communicator.unrealcv import UnrealCV  # noqa: E402
from simworld.config import Config  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/Desktop/kokopelli/mac_server/Saved/demo_city')
os.makedirs(out, exist_ok=True)

config = Config()
ucv = UnrealCV(port=9000, ip='127.0.0.1', resolution=(1280, 720))
comm = Communicator(ucv)

t = time.time()
comm.generate_world(os.path.join(SIMWORLD, 'data/example_city/demo_city_1/progen_world.json'),
                    config['citygen.ue_asset_path'], run_time=False)
print(f'generate_world: {time.time() - t:.1f}s, {len(ucv.client.request("vget /objects").split())} objects')

views = {
    'aerial': ((-6000, -6000, 9000), (-40, 45, 0)),
    'street': ((0, 0, 200), (-3, 30, 0)),
    'high': ((2000, 2000, 25000), (-89, 0, 0)),
}
ucv.set_camera_resolution(0, (1280, 720))
for name, (location, rotation) in views.items():
    ucv.set_camera_location(0, location)
    ucv.set_camera_rotation(0, rotation)
    time.sleep(0.5)
    t = time.time()
    img = ucv.get_image(0, 'lit')
    print(f'{name}: lit {img.shape} in {time.time() - t:.2f}s')
    cv2.imwrite(os.path.join(out, f'{name}.png'), img)
cv2.imwrite(os.path.join(out, 'aerial_mask.png'), ucv.get_image(0, 'object_mask'))
print('saved to', out)
