#!/usr/bin/env python3
"""Manage megacalendar users from the command line (uses the same database settings as the app).

    python scripts/manage_users.py list
    python scripts/manage_users.py create alice --password secret1 --limit 3 --first-name Alice --email a@example.com
    python scripts/manage_users.py set-password master --password 'new-strong-password'
    python scripts/manage_users.py set-limit alice --limit 10          (omit --limit for unlimited)
    python scripts/manage_users.py deactivate alice | activate alice
    python scripts/manage_users.py delete alice

Run with the same DB_TYPE / DB_HOST / DB_USER / DB_PASSWORD (or DATABASE_URL) as the application.
The master user (master / master) is created automatically when the application or this script
first touches the database; use `set-password master` to change the default password.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from megacalendar.auth import hash_password
from megacalendar.db import SessionLocal, init_db
from megacalendar.models import User
from megacalendar.schemas import UserCreate
from megacalendar import service


def _password(args) -> str:
    if args.password:
        return args.password
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("passwords do not match")
    return pw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    c = sub.add_parser("create")
    c.add_argument("username")
    c.add_argument("--password")
    c.add_argument("--limit", type=int, default=1, help="max projects (default 1)")
    c.add_argument("--first-name")
    c.add_argument("--last-name")
    c.add_argument("--phone")
    c.add_argument("--email")
    sp = sub.add_parser("set-password")
    sp.add_argument("username")
    sp.add_argument("--password")
    sl = sub.add_parser("set-limit")
    sl.add_argument("username")
    sl.add_argument("--limit", type=int, default=None, help="max projects; omit for unlimited")
    for name in ("activate", "deactivate", "delete"):
        sub.add_parser(name).add_argument("username")
    args = parser.parse_args(argv)

    init_db()
    with SessionLocal() as db:
        if args.command == "list":
            counts = service.project_counts(db)
            for u in service.list_users(db):
                limit = "unlimited" if u.project_limit is None else str(u.project_limit)
                flags = ("master " if u.is_master else "") + ("" if u.is_active else "inactive ")
                print(f"{u.username:<20} projects {counts.get(u.id, 0):>3} / {limit:<9} {u.display_name:<30} {u.email or '':<30} {flags}")
            return 0
        if args.command == "create":
            data = UserCreate(username=args.username, password=_password(args), project_limit=args.limit,
                              first_name=args.first_name, last_name=args.last_name, phone=args.phone, email=args.email)
            service.create_user(db, data)
            print(f"created {args.username} (limit {args.limit})")
            return 0
        user = service.get_user_by_name(db, args.username)
        if user is None:
            sys.exit(f"no such user: {args.username}")
        if args.command == "set-password":
            user.password_hash = hash_password(_password(args))
            db.commit()
            print(f"password of {user.username} changed")
        elif args.command == "set-limit":
            if user.is_master:
                sys.exit("the master user has no project limit")
            user.project_limit = args.limit
            db.commit()
            print(f"limit of {user.username} set to {'unlimited' if args.limit is None else args.limit}")
        elif args.command in ("activate", "deactivate"):
            if user.is_master:
                sys.exit("the master user is always active")
            user.is_active = args.command == "activate"
            db.commit()
            print(f"{user.username} {'activated' if user.is_active else 'deactivated'}")
        elif args.command == "delete":
            service.delete_user(db, user)
            print(f"deleted {args.username} with all projects and files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
