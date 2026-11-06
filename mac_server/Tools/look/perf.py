import time, sys
from unrealcv import Client
c = Client(("127.0.0.1", 9002)); c.connect()
def fps(label):
    time.sleep(4)
    vals = []
    for _ in range(6):
        vals.append(c.request("vget /look/fps")); time.sleep(0.5)
    print(label, vals[-3:])
c.request("vset /camera/0/location 3400 3400 420"); c.request("vset /camera/0/rotation -6 -135 0")
objs = [o for o in c.request("vget /objects").split() if o.startswith("LK")]
print("objects", len(objs))
fps("solarpunk mats, idle")
if "--swap" in sys.argv:
    for o in objs:
        c.request(f"vset /object/{o}/material /Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial")
    fps("BasicShapeMaterial, idle")
    for o in objs:
        c.request(f"vset /object/{o}/hide")
    fps("all test objects hidden")
