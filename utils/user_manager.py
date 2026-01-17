from pathlib import Path
from typing import List, Dict, Optional

import bcrypt

from utils.path_utils import get_base_dir

def _resolve(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        cwd_path = Path.cwd() / p
        if cwd_path.exists() or not (get_base_dir() / p).exists():
            return cwd_path
        p = get_base_dir() / p
    return p


def load_users(file_path: str | Path = "data/users.txt") -> List[Dict[str, str]]:
    """Load users from a CSV-like text file.

    Each line in the file should have the format:
    username,password,role,team_id
    """
    file_path = _resolve(file_path)
    users: List[Dict[str, str]] = []
    if not file_path.exists():
        return users

    users_by_name: Dict[str, Dict[str, str]] = {}
    with file_path.open("r") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 4:
                continue
            username, password, role, team_id = parts
            if username in users_by_name:
                users_by_name.pop(username, None)
            users_by_name[username] = {
                "username": username,
                "password": password,
                "role": role,
                "team_id": team_id,
            }
    users.extend(users_by_name.values())
    return users


def add_user(
    username: str,
    password: str,
    role: str,
    team_id: str = "",
    file_path: str | Path = "data/users.txt",
) -> None:
    """Add a new user to the users file.

    Raises:
        ValueError: If the username already exists or the team is already
        managed by another owner.
    """
    username = username.strip()
    password = password.strip()
    role = role.strip()
    team_id = team_id.strip()

    file_path = _resolve(file_path)
    users = load_users(file_path)

    if any(u["username"] == username for u in users):
        raise ValueError("Username already exists")

    if role == "owner" and team_id:
        if any(u["role"] == "owner" and u["team_id"] == team_id for u in users):
            raise ValueError("Team already has an owner")

    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()

    with file_path.open("a") as f:
        f.write(f"{username},{hashed_pw},{role},{team_id}\n")


def update_user(
    username: str,
    new_password: Optional[str] = None,
    new_team_id: Optional[str] = None,
    file_path: str | Path = "data/users.txt",
    *,
    new_role: Optional[str] = None,
) -> None:
    """Update an existing user's password or team assignment.

    Parameters
    ----------
    username: str
        The username of the account to modify.
    new_password: str | None
        New password for the user. If ``None`` the password is unchanged.
    new_team_id: str | None
        New team for the user. If ``None`` the team is unchanged. An empty
        string removes the team assignment.
    file_path: str
        Path to the users file.
    new_role: str | None
        Optionally change the user role (e.g., 'admin' or 'owner'). When
        promoting to 'owner', team ownership conflicts are validated.

    Raises
    ------
    ValueError
        If the user does not exist or if assigning an owner to a team that
        already has an owner.
    """

    username = username.strip()
    if new_password is not None:
        new_password = new_password.strip()
    if new_team_id is not None:
        new_team_id = new_team_id.strip()

    file_path = _resolve(file_path)
    users = load_users(file_path)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        raise ValueError("User not found")

    # Handle role change first (so team validation can use final role)
    if new_role is not None:
        new_role = new_role.strip().lower()
        if new_role not in {"admin", "owner"}:
            raise ValueError("Invalid role; must be 'admin' or 'owner'")
        # If promoting to owner, ensure no conflict with existing owners
        if new_role == "owner":
            team_for_user = new_team_id if new_team_id is not None else user.get("team_id", "")
            if team_for_user:
                if any(
                    u["username"] != username and u["role"] == "owner" and u.get("team_id", "") == team_for_user
                    for u in users
                ):
                    raise ValueError("Team already has an owner")
        user["role"] = new_role

    # Check for team ownership conflicts when assigning/moving owners
    if new_team_id is not None:
        if user["role"] == "owner" and new_team_id:
            if any(
                u["username"] != username and u["role"] == "owner" and u.get("team_id", "") == new_team_id
                for u in users
            ):
                raise ValueError("Team already has an owner")
        user["team_id"] = new_team_id

    if new_password is not None:
        hashed_pw = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode()
        user["password"] = hashed_pw

    # Rewrite file with updated user data
    with file_path.open("w") as f:
        for u in users:
            f.write(f"{u['username']},{u['password']},{u['role']},{u['team_id']}\n")


def clear_users(file_path: str | Path = "data/users.txt") -> None:
    """Reset the users file to contain only the admin account.

    If ``file_path`` exists, any existing users are discarded and the file is
    rewritten with only the line beginning with ``"admin,"``. If no such line
    exists, a default admin account of ``admin,pass,admin,`` is written.
    The directory for ``file_path`` is created if it does not already exist.
    """
    admin_line = None
    file_path = _resolve(file_path)
    if file_path.exists():
        with file_path.open("r") as f:
            for line in f:
                if line.startswith("admin,"):
                    admin_line = line.strip()
                    break

    if admin_line is None:
        # Store a default admin user with the known password ``pass``.  The
        # password is intentionally left in plain text so that a fresh league
        # can always be accessed even when the optional ``bcrypt`` dependency
        # is not available.
        admin_line = "admin,pass,admin,"

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w") as f:
        f.write(admin_line.rstrip("\n") + "\n")
