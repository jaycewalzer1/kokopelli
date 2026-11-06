import sys
from unrealcv import Client
c = Client(("127.0.0.1", 9002)); c.connect()
for cmd in sys.argv[1:]:
    r = c.request(cmd)
    print(cmd, "->", r if isinstance(r, str) else f"<{len(r)} bytes>")
