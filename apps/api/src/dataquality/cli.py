"""The ``dataquality`` command: every service and admin task in one entry point. (The
``dq`` command for CI is ``dataquality.client.cli``.)"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys


def _uvicorn(target: str, args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        target,
        factory=True,
        host=args.host,
        port=args.port,
        workers=1,  # one process per container: metrics and in-process state stay exact
        proxy_headers=True,
        # Only trust X-Forwarded-For from the load balancer's network (the VPC CIDR on AWS).
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


def _serve(args: argparse.Namespace) -> None:
    _uvicorn("dataquality.main:create_app", args)


def _worker(_: argparse.Namespace) -> None:
    from dataquality.worker import main

    asyncio.run(main())


def _migrate(_: argparse.Namespace) -> None:
    from dataquality.core.config import get_settings
    from dataquality.migrations.runner import upgrade

    upgrade(get_settings().database_url)
    print("migrations applied")


def _revision(args: argparse.Namespace) -> None:
    from dataquality.core.config import get_settings
    from dataquality.migrations.runner import revision

    revision(get_settings().database_url, args.message)


async def _create_admin(email: str, name: str, password: str) -> None:
    from sqlalchemy import func, select

    from dataquality.core.config import get_settings
    from dataquality.core.db import Database, import_all_models
    from dataquality.core.security import hash_password, password_problems
    from dataquality.users.models import User

    if problems := password_problems(password):
        sys.exit("password needs " + ", ".join(problems))
    import_all_models()
    db = Database(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        async with db.sessionmaker() as session:
            existing = await session.scalar(
                select(User).where(func.lower(User.email) == email.lower())
            )
            if existing:
                existing.role = "admin"
                existing.password_hash = hash_password(password)
                existing.disabled = False
                existing.session_version += 1
                print(f"updated {email} (admin)")
            else:
                session.add(
                    User(
                        email=email.lower(),
                        name=name,
                        role="admin",
                        password_hash=hash_password(password),
                    )
                )
                print(f"created {email} (admin)")
            await session.commit()
    finally:
        await db.dispose()


def _admin(args: argparse.Namespace) -> None:
    password = os.environ.get("DATAQUALITY_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    asyncio.run(_create_admin(args.email, args.name, password))


def _seed(args: argparse.Namespace) -> None:
    from dataquality.demo.seed import run

    asyncio.run(run())


def _openapi(_: argparse.Namespace) -> None:
    from dataquality.openapi import spec, to_yaml

    sys.stdout.write(to_yaml(spec()))


def _server(
    sub: argparse._SubParsersAction[argparse.ArgumentParser], name: str, fn: object, help_: str
) -> None:
    p = sub.add_parser(name, help=help_)
    p.add_argument("--host", default="0.0.0.0")  # noqa: S104 containers listen on all interfaces
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    p.set_defaults(fn=fn)


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="dataquality", description="Euron Open DataQuality")
    sub = parser.add_subparsers(dest="command", required=True)
    _server(sub, "serve", _serve, "the API")
    sub.add_parser(
        "worker", help="the scan worker: scans, schedules, alerts, retention"
    ).set_defaults(fn=_worker)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=_migrate)
    p = sub.add_parser("revision", help="autogenerate a migration from the models")
    p.add_argument("-m", "--message", required=True)
    p.set_defaults(fn=_revision)
    p = sub.add_parser("create-admin", help="create or reset an admin account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Admin")
    p.set_defaults(fn=_admin)
    sub.add_parser(
        "seed-demo", help="demo users, projects, sources, datasets, checks and history"
    ).set_defaults(fn=_seed)
    sub.add_parser("openapi", help="print the OpenAPI document as YAML").set_defaults(fn=_openapi)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
