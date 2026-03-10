from pathlib import Path
from typing import List, Dict, Optional, Any
import json

import bcrypt

from utils.path_utils import get_data_root, resolve_app_path

_BOOTSTRAP_FILENAME = "admin_bootstrap.json"
_SETUP_REQUIRED_SENTINEL = "__setup_required__"

def _resolve(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        parts = p.parts
        if parts and parts[0].lower() == "data":
            return resolve_app_path(p)
        cwd_path = Path.cwd() / p
        if cwd_path.exists():
            return cwd_path
        p = resolve_app_path(p)
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


def _bootstrap_path(data_root: str | Path | None = None) -> Path:
    if data_root is None:
        return get_data_root() / _BOOTSTRAP_FILENAME
    return Path(data_root) / _BOOTSTRAP_FILENAME


def load_admin_bootstrap(data_root: str | Path | None = None) -> Dict[str, Any]:
    path = _bootstrap_path(data_root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_admin_bootstrap(
    *,
    data_root: str | Path | None = None,
    password_hash: str | None = None,
    password_scheme: str | None = None,
    password_plaintext: str | None = None,
    require_setup: bool | None = None,
) -> Dict[str, Any]:
    payload = load_admin_bootstrap(data_root)
    if password_hash is not None:
        if str(password_hash).strip():
            payload["password_hash"] = str(password_hash)
        else:
            payload.pop("password_hash", None)
    if password_scheme is not None:
        if str(password_scheme).strip():
            payload["password_scheme"] = str(password_scheme)
        else:
            payload.pop("password_scheme", None)
    if password_plaintext is not None:
        if str(password_plaintext).strip():
            payload["password"] = str(password_plaintext)
        else:
            payload.pop("password", None)
    if require_setup is not None:
        payload["require_setup"] = bool(require_setup)
    path = _bootstrap_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def _bootstrap_password_hash(data_root: str | Path | None = None) -> str:
    payload = load_admin_bootstrap(data_root)
    stored_hash = str(payload.get("password_hash") or "").strip()
    if stored_hash:
        return stored_hash

    plain = str(payload.get("password") or "").strip()
    if not plain:
        return ""

    hashed = _hash_password(plain)
    save_admin_bootstrap(
        data_root=data_root,
        password_hash=hashed,
        password_scheme="bcrypt",
        password_plaintext="",
        require_setup=False,
    )
    return hashed


def admin_password_setup_required(
    file_path: str | Path = "data/users.txt",
    *,
    data_root: str | Path | None = None,
) -> bool:
    payload = load_admin_bootstrap(data_root)
    if not bool(payload.get("require_setup")):
        return False
    users = load_users(file_path)
    admin = next((u for u in users if u["username"] == "admin"), None)
    if admin is None:
        return True
    return str(admin.get("password") or "").strip() in {"", "pass", _SETUP_REQUIRED_SENTINEL}


def set_admin_password(
    password: str,
    file_path: str | Path = "data/users.txt",
    *,
    data_root: str | Path | None = None,
) -> None:
    password = password.strip()
    if not password:
        raise ValueError("Administrator password is required.")

    file_path = _resolve(file_path)
    users = load_users(file_path)
    hashed_pw = _hash_password(password)

    admin = next((u for u in users if u["username"] == "admin"), None)
    if admin is None:
        users.insert(
            0,
            {
                "username": "admin",
                "password": hashed_pw,
                "role": "admin",
                "team_id": "",
            },
        )
    else:
        admin["password"] = hashed_pw
        admin["role"] = "admin"
        admin["team_id"] = ""

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        for user in users:
            f.write(
                f"{user['username']},{user['password']},{user['role']},{user['team_id']}\n"
            )

    save_admin_bootstrap(
        data_root=data_root,
        password_hash=hashed_pw,
        password_scheme="bcrypt",
        password_plaintext="",
        require_setup=False,
    )


def apply_admin_bootstrap(
    file_path: str | Path = "data/users.txt",
    *,
    data_root: str | Path | None = None,
) -> bool:
    file_path = _resolve(file_path)
    payload = load_admin_bootstrap(data_root)
    if bool(payload.get("require_setup")):
        return False

    bootstrap_hash = _bootstrap_password_hash(data_root)
    if not bootstrap_hash:
        return False

    users = load_users(file_path)
    admin = next((u for u in users if u["username"] == "admin"), None)
    if admin is None:
        return False

    current_password = str(admin.get("password") or "").strip()
    if current_password not in {"", "pass", _SETUP_REQUIRED_SENTINEL}:
        return False

    admin["password"] = bootstrap_hash
    admin["role"] = "admin"
    admin["team_id"] = ""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        for user in users:
            f.write(
                f"{user['username']},{user['password']},{user['role']},{user['team_id']}\n"
            )
    return True


def verify_user_password(password: str, stored_value: str) -> bool:
    clean_password = password.strip()
    stored = str(stored_value or "")
    if not stored:
        return False
    try:
        if bcrypt.checkpw(clean_password.encode("utf-8"), stored.encode("utf-8")):
            return True
    except ValueError:
        pass
    except Exception:
        pass
    return clean_password == stored


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

    hashed_pw = _hash_password(password)

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
        hashed_pw = _hash_password(new_password)
        user["password"] = hashed_pw

    # Rewrite file with updated user data
    with file_path.open("w") as f:
        for u in users:
            f.write(f"{u['username']},{u['password']},{u['role']},{u['team_id']}\n")


def clear_users(file_path: str | Path = "data/users.txt") -> None:
    """Reset the users file to contain only the admin account.

    If ``file_path`` exists, any existing users are discarded and the file is
    rewritten with only the line beginning with ``"admin,"``. If no such line
    exists, an installer/bootstrap admin password is used when configured;
    otherwise a default admin account of ``admin,pass,admin,`` is written.
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
        bootstrap = load_admin_bootstrap()
        if bool(bootstrap.get("require_setup")):
            admin_line = f"admin,{_SETUP_REQUIRED_SENTINEL},admin,"
        else:
            bootstrap_hash = _bootstrap_password_hash()
            if bootstrap_hash:
                admin_line = f"admin,{bootstrap_hash},admin,"
            else:
                # Preserve a known fallback for development and legacy installs
                # when no installer/bootstrap configuration exists.
                admin_line = "admin,pass,admin,"

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w") as f:
        f.write(admin_line.rstrip("\n") + "\n")
