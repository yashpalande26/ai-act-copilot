import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

# Note: EUR-Lex sometimes serves an AWS WAF JavaScript challenge page instead
# of the real document to automated requests (HTTP 202, empty/near-empty
# body, a page containing "awsWafCookie"). If that happens, this script will
# "succeed" but save a useless file — check the printed size/hash look
# plausible (real page is several hundred KB). When blocked, download the
# URL manually in a real browser and save it to OUTPUT_PATH instead.
URL = (
    "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02024R1689-20260727"
)
OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "aiact_02024R1689-20260727.html"
)


def fetch() -> None:
    request = Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request) as response:
        content = response.read()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(content)

    print(f"Saved to {OUTPUT_PATH}")
    print(f"Size: {len(content)} bytes")
    print(f"SHA-256: {hashlib.sha256(content).hexdigest()}")


if __name__ == "__main__":
    fetch()
