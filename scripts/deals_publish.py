"""Send signed editorial batches without accessing the bot or payment tokens.

Usage: python scripts/deals_publish.py --credentials PRIVATE.json --status
       python scripts/deals_publish.py --credentials PRIVATE.json --batch BATCH.json --dry-run
       python scripts/deals_publish.py --credentials PRIVATE.json --batch BATCH.json
The private credentials must never be committed or printed.
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--batch")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.status == bool(args.batch):
        parser.error("choose either --status or --batch")
    credentials = json.loads(Path(args.credentials).read_text())
    base = credentials["base_url"].rstrip("/")
    if urlsplit(base).scheme != "https":
        parser.error("HTTPS endpoint required")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(credentials["private_key"]))
    url = base + ("/status" if args.status else "")
    method, body = "GET", b""
    if args.batch:
        batch = json.loads(Path(args.batch).read_text())
        if args.dry_run:
            batch["dry_run"] = True
        body = json.dumps(batch, ensure_ascii=False, separators=(",", ":")).encode()
        method = "POST"
    stamp = str(int(time.time()))
    message = f"v1\n{stamp}\n{method}\n{urlsplit(url).path}\n{hashlib.sha256(body).hexdigest()}".encode()
    request = urllib.request.Request(url, data=body if method == "POST" else None,
        method=method, headers={"Content-Type": "application/json",
            "X-Editorial-Timestamp": stamp,
            "X-Editorial-Signature": key.sign(message).hex()})
    # A redirect must never move a signed publication to another destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=180) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print(json.dumps({"ok": False, "http_status": exc.code,
            "response": exc.read(4096).decode(errors="replace")}, ensure_ascii=False))
        raise SystemExit(1)
    except (urllib.error.URLError, TimeoutError):
        print(json.dumps({"ok": False, "state": "delivery_unknown", "action": "query status; do not change ids"}))
        raise SystemExit(2)
    print(json.dumps(result, ensure_ascii=False))
    if result.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
