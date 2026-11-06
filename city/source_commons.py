"""Put photos of real green buildings from Wikimedia Commons up for review on the city moodboard.

Real places keep the board grounded. These are the buildings, and the architects' built work, that Are.na has no channels for.
Every picture keeps its license and author in its origin.

    .venv/bin/python city/source_commons.py --per-search 8
"""
import argparse
import base64
import html
import json
import re
import time
import urllib.parse
import urllib.request

from source_arena import HEADERS

API = "https://commons.wikimedia.org/w/api.php"
# A search per place. The architects' names go in by their built work, since Commons files are named for buildings.
SEARCHES = {
    "Bosco Verticale, Milan (Stefano Boeri)": "Bosco Verticale",
    "Vertical Forest, Tirana (Stefano Boeri)": "Vertical Forest Tirana",
    "Trudo Vertical Forest, Eindhoven (Stefano Boeri)": "Trudo Vertical Forest Eindhoven",
    "Gardens by the Bay, Singapore": "Supertree Grove Gardens by the Bay",
    "Cloud Forest, Gardens by the Bay": "Cloud Forest dome Gardens by the Bay",
    "Parkroyal Collection Pickering, Singapore (WOHA)": "Parkroyal Pickering",
    "Kampung Admiralty, Singapore (WOHA)": "Kampung Admiralty",
    "Oasia Hotel Downtown, Singapore (WOHA)": "Oasia Hotel Downtown",
    "SkyVille @ Dawson, Singapore (WOHA)": "SkyVille Dawson",
    "Tao Zhu Yin Yuan, Taipei (Vincent Callebaut)": "Tao Zhu Yin Yuan",
}
OPEN = re.compile(r"^(CC0|CC BY(-SA)? [\d.]+|Public domain|PD.*)", re.I)


def files(term, limit):
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrsearch": f"{term} filetype:bitmap",
              "gsrlimit": limit, "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1200}
    time.sleep(2)
    with urllib.request.urlopen(urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers=HEADERS), timeout=30) as response:
        pages = json.load(response).get("query", {}).get("pages", {})
    return sorted(pages.values(), key=lambda page: page.get("index", 0))


def plain(markup):
    return html.unescape(re.sub(r"<[^>]+>", "", markup or "")).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-search", type=int, default=8)
    parser.add_argument("--place", help="only the searches whose place name contains this")
    parser.add_argument("--panel", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    added = repeats = skipped = 0
    for place, term in SEARCHES.items():
        if args.place and args.place.lower() not in place.lower():
            continue
        try:
            pages = files(term, args.per_search)
        except OSError as error:
            # Commons limits how fast one client can search. Skip the place and say so, rather than lose the rest.
            print(f"{place}: search failed, run again with --place: {error}", flush=True)
            continue
        for page in pages:
            info = page["imageinfo"][0]
            meta = info.get("extmetadata", {})
            license_name = plain(meta.get("LicenseShortName", {}).get("value"))
            if not OPEN.match(license_name):
                skipped += 1
                continue
            try:
                with urllib.request.urlopen(urllib.request.Request(info["thumburl"], headers=HEADERS), timeout=60) as response:
                    data = response.read()
                origin = {"site": "commons", "channel": place, "channel_url": info["descriptionurl"],
                          "license": license_name, "author": plain(meta.get("Artist", {}).get("value"))[:120]}
                body = json.dumps({"data": base64.b64encode(data).decode(), "title": page["title"].removeprefix("File:").rsplit(".", 1)[0],
                                   "source": info["descriptionurl"], "origin": origin}).encode()
                request = urllib.request.Request(f"{args.panel}/api/moodboard/add", data=body, method="POST",
                                                 headers={"Content-Type": "application/json", "Origin": args.panel})
                with urllib.request.urlopen(request, timeout=60) as response:
                    result = json.load(response)
            except (OSError, ValueError) as error:
                print(f"  {page['title']} failed: {error}", flush=True)
                continue
            repeats += bool(result.get("duplicate"))
            added += not result.get("duplicate")
        print(f"{place}: added {added}, repeats {repeats}, not openly licensed {skipped}", flush=True)


if __name__ == "__main__":
    main()
