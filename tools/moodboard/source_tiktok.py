"""Put slides from TikTok photo posts up for review on the city moodboard.

TikTok's search only works in a signed-in browser, so the post list comes from there (one "user id" per line or
semicolon). Each post's own page carries its slides, which this reads without signing in.

    .venv/bin/python tools/moodboard/source_tiktok.py out/moodboard/tiktok_posts.txt --count 300
"""
import argparse
import base64
import json
import re
import time
import urllib.request
from pathlib import Path

import source_arena  # noqa: F401  (sets up certificates for every request)

# TikTok serves the post's data only to something that looks like a browser.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
DATA = re.compile(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)


def fetch(url):
    time.sleep(1)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as response:
        return response.read()


def slides(user, post_id):
    page = fetch(f"https://www.tiktok.com/@{user}/video/{post_id}").decode()
    item = json.loads(DATA.search(page).group(1))["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
    urls = [image["imageURL"]["urlList"][0] for image in (item.get("imagePost") or {}).get("images", [])]
    return item.get("desc", ""), urls


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("posts", type=Path)
    parser.add_argument("--count", type=int, default=300, help="new pictures to add")
    parser.add_argument("--per-post", type=int, default=3, help="most slides to take from one post")
    parser.add_argument("--panel", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    posts = [entry.split() for entry in re.split(r"[;\n]", args.posts.read_text()) if entry.strip()]
    posts = list(dict.fromkeys(map(tuple, posts)))
    found = []
    for user, post_id in posts:
        try:
            desc, urls = slides(user, post_id)
        except (OSError, ValueError, KeyError, AttributeError) as error:
            print(f"  @{user}/{post_id} unreadable: {error!r}", flush=True)
            continue
        found.append((user, post_id, desc, urls[:args.per_post]))
    print(f"{sum(len(urls) for *_, urls in found)} slides from {len(found)} of {len(posts)} posts", flush=True)

    added = repeats = failed = 0
    # The first slide of every post, then the second of every post, so no one account fills the board.
    for index in range(args.per_post):
        for user, post_id, desc, urls in found:
            if index >= len(urls) or added >= args.count:
                continue
            post = f"https://www.tiktok.com/@{user}/photo/{post_id}"
            try:
                data = fetch(urls[index])
                body = json.dumps({"data": base64.b64encode(data).decode(), "title": " ".join(desc.split())[:140], "source": post,
                                   "origin": {"site": "tiktok", "channel": f"@{user}", "channel_url": post, "slide": index + 1}}).encode()
                request = urllib.request.Request(f"{args.panel}/api/moodboard/add", data=body, method="POST",
                                                 headers={"Content-Type": "application/json", "Origin": args.panel})
                with urllib.request.urlopen(request, timeout=60) as response:
                    result = json.load(response)
            except (OSError, ValueError) as error:
                failed += 1
                print(f"  {post} slide {index + 1} failed: {error!r}", flush=True)
                continue
            repeats += bool(result.get("duplicate"))
            added += not result.get("duplicate")
        print(f"slide {index + 1} of each post done: added {added}, repeats {repeats}, failed {failed}", flush=True)


if __name__ == "__main__":
    main()
