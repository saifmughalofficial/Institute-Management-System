"""Server-side administrator recovery: python -m ims.cli reset-password <username>"""
import getpass
import sys

from . import db
from .actor import audit
from .security import hash_password, password_problems


def main(argv):
    if len(argv) != 2 or argv[0] != "reset-password":
        print(__doc__)
        return 1
    db.init_db()
    user = db.query_one("SELECT * FROM users WHERE username=?", (argv[1],))
    if not user:
        print("No such user.")
        return 1
    pw = getpass.getpass("New password: ")
    if password_problems(pw) or pw != getpass.getpass("Repeat: "):
        print("Password too weak or does not match.")
        return 1
    db.execute("UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL, is_active=1, "
               "must_change_password=0 WHERE id=?", (hash_password(pw), user["id"]))
    audit(user["institution_id"], None, "password_reset_cli", "user", user["id"])
    print("Password reset.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
