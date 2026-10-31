"""
users.py - operator tool for accounts (password resets, disabling an account).

    python -m backend.users add asha_worker1                  (prompts for a password)
    python -m backend.users list
    python -m backend.users passwd asha_worker1
    python -m backend.users disable asha_worker1        |   enable asha_worker1

Every account is an ordinary user: it can see ONLY its own saved results. There are no staff or admin accounts.
People normally create their own free account on the website; this tool is for password resets and support.
"""
import argparse
import getpass
import sys

from backend import config, security, store


def add_user(username: str, password: str) -> None:
    username = username.strip().lower()
    if not username or len(username) > 64 or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise ValueError("username must be 1-64 letters, digits, '.', '_' or '-'")
    problem = security.password_problem(password, config.MIN_USER_PASSWORD_LEN)
    if problem:
        raise ValueError(problem)
    if store.get_user(username):
        raise ValueError(f"user '{username}' already exists")
    store.create_user(username, security.hash_password(password), "user")
    store.audit("cli", "user_created", username)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("username")
    sub.add_parser("list")
    for name in ("passwd", "disable", "enable"):
        p = sub.add_parser(name); p.add_argument("username")
    args = ap.parse_args(argv)
    store.init_db()
    try:
        if args.cmd == "add":
            pw = getpass.getpass(f"Password (min {config.MIN_USER_PASSWORD_LEN} characters): ")
            if pw != getpass.getpass("Repeat password: "):
                sys.exit("Passwords do not match")
            add_user(args.username, pw)
            print(f"Created account '{args.username.strip().lower()}'")
        elif args.cmd == "list":
            for u in store.list_users():
                print(f"{u['username']:<24} {'DISABLED' if u['disabled'] else 'active'}")
        elif args.cmd == "passwd":
            pw = getpass.getpass("New password: ")
            problem = security.password_problem(pw)
            if problem:
                sys.exit(problem)
            ok = store.set_user_password(args.username.lower(), security.hash_password(pw))
            store.audit("cli", "password_reset", args.username.lower())
            print("Password updated" if ok else "No such user")
        else:
            ok = store.set_user_disabled(args.username.lower(), args.cmd == "disable")
            store.audit("cli", f"user_{args.cmd}d", args.username.lower())
            print("Done" if ok else "No such user")
    except ValueError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
