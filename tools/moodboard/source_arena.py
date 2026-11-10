"""Put solarpunk pictures from Are.na up for review on the city moodboard.

Finds public Are.na channels by search, takes their image blocks in turns so no one channel fills the board,
and adds each one through the running dev panel, which keeps one copy of any picture seen twice.

    .venv/bin/python tools/moodboard/source_arena.py --count 500
    .venv/bin/python tools/moodboard/source_arena.py --channel animation-backgrounds-ghibli --per-channel 30 --count 30
"""
import argparse
import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import certifi

# The python.org build doesn't use the system's root certificates, so name certifi's for every request.
urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))))

API = "https://api.are.na/v2"
HEADERS = {"User-Agent": "kokopelli-moodboard/0.1"}
QUERIES = ["solarpunk", "solar punk", "solarpunk architecture", "solarpunk city", "eco futurism", "green city future"]
PER_CHANNEL = 40
PAUSE = 0.3


def get_json(path, tries=4, **params):
    """Are.na's search sometimes times out at its gateway, so a busy or failing server gets a few more tries, further apart."""
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(tries):
        time.sleep(PAUSE * 10 ** min(attempt, 2) * (attempt + 1))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise


def channels(queries, pages=4):
    found = {}
    for query in queries:
        for page in range(1, pages + 1):
            body = get_json("/search/channels", q=query, per=50, page=page)
            for channel in body.get("channels", []):
                if channel.get("status") != "private" and channel.get("length", 0) >= 10:
                    found.setdefault(channel["slug"], channel)
            if page >= body.get("total_pages", 0):
                break
    return sorted(found.values(), key=lambda channel: -channel["length"])


def named(slugs):
    return [get_json(f"/channels/{slug}", per=1) for slug in slugs]


def image_blocks(channel, limit):
    blocks = []
    for page in range(1, 20):
        contents = get_json(f"/channels/{channel['slug']}/contents", per=100, page=page).get("contents", [])
        blocks += [block for block in contents if block.get("class") == "Image" and block.get("image")]
        if len(contents) < 100 or len(blocks) >= limit:
            break
    return blocks[:limit]


def in_turns(lists):
    """The first block of every channel, then the second of every channel, and so on."""
    for index in range(max(map(len, lists), default=0)):
        for blocks in lists:
            if index < len(blocks):
                yield blocks[index]


def download(block):
    with urllib.request.urlopen(urllib.request.Request(block["image"]["display"]["url"], headers=HEADERS), timeout=60) as response:
        return response.read()


def add(panel, block, data):
    channel = block["_channel"]
    origin = {"site": "are.na", "block": block["id"], "channel": channel["title"],
              "channel_url": f"https://www.are.na/{channel['user']['slug']}/{channel['slug']}",
              "original": (block.get("source") or {}).get("url") or ""}
    title = block.get("title") or ""
    # Are.na fills an untitled upload's title with its file name, which says nothing.
    if title == block["image"].get("filename") or "." in title[-5:]:
        title = ""
    body = json.dumps({"data": base64.b64encode(data).decode(), "title": title,
                       "source": f"https://www.are.na/block/{block['id']}", "origin": origin}).encode()
    request = urllib.request.Request(f"{panel}/api/moodboard/add", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Origin": panel})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=500, help="new pictures to add")
    parser.add_argument("--query", action="append", help="search Are.na for channels with this; repeatable (default: solarpunk terms)")
    parser.add_argument("--channel", action="append", help="take this channel slug instead of searching; repeatable")
    parser.add_argument("--per-channel", type=int, default=PER_CHANNEL)
    parser.add_argument("--panel", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    found = named(args.channel) if args.channel else channels(args.query or QUERIES)
    print(f"{len(found)} channels", flush=True)
    lists = []
    for channel in found:
        try:
            blocks = image_blocks(channel, args.per_channel)
        except OSError as error:
            print(f"skip {channel['slug']}: {error}", flush=True)
            continue
        for block in blocks:
            block["_channel"] = channel
        lists.append(blocks)
        if sum(map(len, lists)) >= args.count * 2:
            break
    seen, queue = set(), []
    for block in in_turns(lists):
        if block["id"] not in seen:
            seen.add(block["id"])
            queue.append(block)
    print(f"{len(queue)} image blocks from {len(lists)} channels", flush=True)

    added = repeats = failed = 0
    with ThreadPoolExecutor(4) as pool:
        for start in range(0, len(queue), 8):
            batch = queue[start:start + 8]
            for block, data in zip(batch, pool.map(lambda block: _try(download, block), batch)):
                if data is None:
                    failed += 1
                    continue
                result = _try(add, args.panel, block, data)
                if result is None:
                    failed += 1
                elif result.get("duplicate"):
                    repeats += 1
                else:
                    added += 1
            print(f"added {added}, repeats {repeats}, failed {failed}", flush=True)
            if added >= args.count:
                break


def _try(function, *args):
    try:
        return function(*args)
    except (OSError, ValueError) as error:
        print(f"  {function.__name__} failed: {error}", flush=True)
        return None


if __name__ == "__main__":
    main()
