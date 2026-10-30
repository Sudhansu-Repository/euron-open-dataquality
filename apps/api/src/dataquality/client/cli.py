"""``dq``: DataQuality from a terminal or a CI job, with a project API key.

    export DQ_URL=https://dq.example.com DQ_API_KEY=dq_... DQ_PROJECT=<project id>
    dq scan customers --fail-on error          # scan, wait, exit 1 if an error check fails
    dq checks apply customers dq/customers.yaml --prune
    dq checks export customers > dq/customers.yaml
    dq push signups events.json                # validate a batch of records

Exit codes: 0 passed, 1 the quality gate failed, 2 usage or connection problem.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

PASS, GATE, ERROR = 0, 1, 2


class CliError(Exception):
    pass


def _client(args: argparse.Namespace) -> httpx.Client:
    if not args.key:
        raise CliError("set DQ_API_KEY (or --key) to a project API key")
    return httpx.Client(
        base_url=args.url.rstrip("/"),
        headers={"authorization": f"Bearer {args.key}"},
        timeout=args.timeout + 30,
    )


def _check(resp: httpx.Response) -> Any:
    if resp.status_code >= 400:
        try:
            message = resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = resp.text[:300]
        raise CliError(f"HTTP {resp.status_code}: {message}")
    return resp.json() if "json" in resp.headers.get("content-type", "") else resp.text


def _dataset_id(c: httpx.Client, project: str, name: str) -> str:
    for d in _check(c.get(f"/api/v1/projects/{project}/datasets")):
        if name in (d["id"], d["slug"], d["name"]):
            return str(d["id"])
    raise CliError(f"no dataset {name!r} in the project")


def _report(scan: dict[str, Any], out: Any) -> None:
    score = "n/a" if scan.get("score") is None else f"{scan['score']:.1f}%"
    out.write(
        f"{scan.get('dataset_name') or scan['dataset_id']}: {scan['status']}, score "
        f"{score}, {scan.get('row_count') or 0:,} rows\n"
    )
    for r in scan.get("results", []):
        mark = {
            "pass": "ok  ",
            "fail": "FAIL" if r["severity"] == "error" else "warn",
            "error": "ERR ",
        }[r["status"]]
        out.write(f"  {mark} {r['check_name']}: {r['error'] or r['message']}\n")
    if scan.get("error"):
        out.write(f"  error: {scan['error']}\n")


def _gate(scan: dict[str, Any], fail_on: str) -> int:
    if scan["status"] != "succeeded":
        return GATE
    results = scan.get("results", [])
    if fail_on == "none":
        return PASS
    if any(
        r["status"] == "fail" and (r["severity"] == "error" or fail_on == "warn") for r in results
    ):
        return GATE
    return PASS


def cmd_scan(args: argparse.Namespace) -> int:
    with _client(args) as c:
        did = _dataset_id(c, args.project, args.dataset)
        body = {"idempotency_key": args.idempotency_key} if args.idempotency_key else None
        scan = _check(
            c.post(
                f"/api/v1/projects/{args.project}/datasets/{did}/scans",
                params={"wait": min(args.timeout, 300)},
                json=body,
            )
        )
    if args.json:
        sys.stdout.write(json.dumps(scan, indent=2) + "\n")
    else:
        _report(scan, sys.stdout)
    if scan["status"] in ("queued", "running"):
        sys.stderr.write(
            f"the scan did not finish in {args.timeout}s; it keeps running (id {scan['id']})\n"
        )
        return GATE
    return _gate(scan, args.fail_on)


def cmd_push(args: argparse.Namespace) -> int:
    with open(args.file, encoding="utf-8") as f:
        text = f.read()
    records = (
        json.loads(text)
        if text.lstrip().startswith("[")
        else [json.loads(line) for line in text.splitlines() if line.strip()]
    )
    with _client(args) as c:
        did = _dataset_id(c, args.project, args.dataset)
        out = _check(
            c.post(
                f"/api/v1/projects/{args.project}/datasets/{did}/records",
                params={"wait": min(args.timeout, 120)},
                json={"records": records},
            )
        )
    _report(out["scan"], sys.stdout)
    return _gate(out["scan"], args.fail_on)


def cmd_checks(args: argparse.Namespace) -> int:
    with _client(args) as c:
        did = _dataset_id(c, args.project, args.dataset)
        path = f"/api/v1/projects/{args.project}/datasets/{did}/checks/yaml"
        if args.action == "export":
            sys.stdout.write(_check(c.get(path)))
            return PASS
        with open(args.file, encoding="utf-8") as f:
            result = _check(c.put(path, json={"yaml": f.read(), "prune": args.prune}))
    sys.stdout.write(
        f"created {result['created']}, updated {result['updated']}, removed "
        f"{len(result['removed'])}\n"
    )
    return PASS


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dq", description="Euron Open DataQuality from the command line"
    )
    p.add_argument("--url", default=os.environ.get("DQ_URL", "http://localhost:4930"))
    p.add_argument("--key", default=os.environ.get("DQ_API_KEY", ""))
    p.add_argument("--project", default=os.environ.get("DQ_PROJECT", ""))
    p.add_argument("--timeout", type=float, default=float(os.environ.get("DQ_TIMEOUT", "300")))
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan", help="scan a dataset and wait for the result")
    s.add_argument("dataset", help="dataset id, slug or name")
    s.add_argument("--fail-on", choices=["error", "warn", "none"], default="error")
    s.add_argument("--idempotency-key")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("push", help="validate a batch of records (JSON array or NDJSON file)")
    s.add_argument("dataset")
    s.add_argument("file")
    s.add_argument("--fail-on", choices=["error", "warn", "none"], default="error")
    s.set_defaults(fn=cmd_push)
    s = sub.add_parser("checks", help="checks as code")
    s.add_argument("action", choices=["export", "apply"])
    s.add_argument("dataset")
    s.add_argument("file", nargs="?")
    s.add_argument(
        "--prune", action="store_true", help="apply: delete checks the file no longer lists"
    )
    s.set_defaults(fn=cmd_checks)
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.project:
        sys.stderr.write("set DQ_PROJECT (or --project) to the project id\n")
        sys.exit(ERROR)
    if args.command == "checks" and args.action == "apply" and not args.file:
        sys.stderr.write("dq checks apply <dataset> <file.yaml>\n")
        sys.exit(ERROR)
    try:
        code = args.fn(args)
    except CliError as exc:
        sys.stderr.write(f"dq: {exc}\n")
        code = ERROR
    except httpx.HTTPError as exc:
        sys.stderr.write(f"dq: cannot reach {args.url} ({type(exc).__name__})\n")
        code = ERROR
    sys.exit(code)
