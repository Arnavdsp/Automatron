"""Check a deployed Automatron against the post-deploy expectations.

    python tests/deploy_smoke.py https://automatron-xxxx.run.app [--password PASS]

Read-only: it starts no runs and changes nothing. Exits non-zero on the first
expectation that fails, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 90


def fetch(url: str, auth: tuple[str, str] | None) -> tuple[int, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body[:200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200]
    except Exception as exc:  # noqa: BLE001 - any transport failure is a failed check
        return 0, f"{type(exc).__name__}: {exc}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    auth = (args.username, args.password) if args.password else None
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    print(f"checking {base}")
    print("(a cold start takes tens of seconds; the first call waits for it)")

    status, body = fetch(f"{base}/health", None)
    check("liveness probe answers without credentials", status == 200, f"status {status}")
    if isinstance(body, dict):
        check("four sectors registered", body.get("sectors") == 4, f"got {body.get('sectors')}")

    status, body = fetch(f"{base}/api/v1/health", None)
    check("api health answers", status == 200, f"status {status}")
    if isinstance(body, dict):
        sectors = body.get("sectors") or []
        check("all four sectors named",
              set(sectors) == {"space", "quant", "ecommerce", "realestate"}, str(sectors))
        check("running against real providers, not the fake model",
              body.get("fake_mode") is False,
              "fake_mode is true: no provider key reached the service")

    # With a password set, the API must refuse an anonymous caller. Without one,
    # every route is open, which is worth failing loudly on a public deployment.
    status, _ = fetch(f"{base}/api/v1/sectors", None)
    if auth:
        check("api refuses an anonymous caller", status == 401, f"status {status}")
        status, body = fetch(f"{base}/api/v1/sectors", auth)
        check("api accepts the password", status == 200, f"status {status}")
    else:
        check("api is NOT open to anonymous callers", status == 401,
              "no password given to this script; if the service has none, every route "
              "is public")

    status, body = fetch(f"{base}/api/v1/providers", auth)
    check("provider status is readable", status == 200, f"status {status}")
    if isinstance(body, list) and body:
        healthy = [p for p in body if p.get("state") in ("ok", "ready", "healthy")]
        names = sorted({p.get("provider", "?") for p in body})
        check("at least one provider is usable", bool(healthy),
              f"{len(healthy)} of {len(body)} slots usable across {names}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
