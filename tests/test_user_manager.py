import bcrypt
import pytest
from utils.user_manager import (
    apply_admin_bootstrap,
    add_user,
    admin_password_setup_required,
    clear_users,
    load_admin_bootstrap,
    load_users,
    save_admin_bootstrap,
    set_admin_password,
    update_user,
)


def test_add_user(tmp_path):
    users_file = tmp_path / "users.txt"
    admin_hash = bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode()
    users_file.write_text(f"admin,{admin_hash},admin,\n")

    add_user("newuser", "pw", "owner", "LAX", file_path=str(users_file))

    users = load_users(str(users_file))
    new_user = next(u for u in users if u["username"] == "newuser")
    assert new_user["team_id"] == "LAX"
    assert bcrypt.checkpw(b"pw", new_user["password"].encode())


def test_duplicate_username(tmp_path):
    users_file = tmp_path / "users.txt"
    admin_hash = bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode()
    user_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
    users_file.write_text(f"admin,{admin_hash},admin,\nuser1,{user_hash},owner,LAX\n")

    with pytest.raises(ValueError):
        add_user("user1", "pw", "owner", "ARG", file_path=str(users_file))


def test_duplicate_team(tmp_path):
    users_file = tmp_path / "users.txt"
    admin_hash = bcrypt.hashpw(b"pass", bcrypt.gensalt()).decode()
    user_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
    users_file.write_text(f"admin,{admin_hash},admin,\nuser1,{user_hash},owner,LAX\n")

    with pytest.raises(ValueError):
        add_user("user2", "pw", "owner", "LAX", file_path=str(users_file))


def test_update_password(tmp_path):
    users_file = tmp_path / "users.txt"
    old_hash = bcrypt.hashpw(b"old", bcrypt.gensalt()).decode()
    users_file.write_text(f"user1,{old_hash},owner,LAX\n")

    update_user("user1", new_password="new", file_path=str(users_file))

    users = load_users(str(users_file))
    updated = next(u for u in users if u["username"] == "user1")
    assert bcrypt.checkpw(b"new", updated["password"].encode())


def test_update_team(tmp_path):
    users_file = tmp_path / "users.txt"
    pw_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
    users_file.write_text(f"user1,{pw_hash},owner,LAX\n")

    update_user("user1", new_team_id="ARG", file_path=str(users_file))

    users = load_users(str(users_file))
    assert any(u["username"] == "user1" and u["team_id"] == "ARG" for u in users)


def test_update_team_conflict(tmp_path):
    users_file = tmp_path / "users.txt"
    pw1_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
    pw2_hash = bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode()
    users_file.write_text(
        f"user1,{pw1_hash},owner,LAX\nuser2,{pw2_hash},owner,ARG\n"
    )

    with pytest.raises(ValueError):
        update_user("user1", new_team_id="ARG", file_path=str(users_file))


def test_load_users_prefers_data_dir_for_data_prefix(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd_users = cwd / "data" / "users.txt"
    cwd_users.parent.mkdir(parents=True, exist_ok=True)
    cwd_users.write_text("admin,pass,admin,\n")

    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True, exist_ok=True)
    data_users = data_root / "users.txt"
    data_users.write_text("admin,pass,admin,\nuser1,pass,owner,LAX\n")

    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    import utils.path_utils as path_utils
    path_utils._DATA_DIR = None
    monkeypatch.chdir(cwd)

    users = load_users("data/users.txt")
    assert any(u["username"] == "user1" for u in users)


def test_clear_users_uses_bootstrap_password_for_new_admin(tmp_path, monkeypatch):
    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    save_admin_bootstrap(
        data_root=data_root,
        password_plaintext="secret123",
        require_setup=False,
    )
    users_file = tmp_path / "league_users.txt"

    clear_users(users_file)

    users = load_users(users_file)
    admin = next(u for u in users if u["username"] == "admin")
    assert bcrypt.checkpw(b"secret123", admin["password"].encode())
    bootstrap = load_admin_bootstrap(data_root)
    assert bootstrap.get("password_hash")
    assert not bootstrap.get("password")


def test_set_admin_password_clears_setup_required_bootstrap(tmp_path, monkeypatch):
    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    save_admin_bootstrap(data_root=data_root, require_setup=True)
    users_file = tmp_path / "users.txt"
    users_file.write_text("admin,__setup_required__,admin,\n", encoding="utf-8")

    assert admin_password_setup_required(users_file, data_root=data_root)

    set_admin_password("new-secret", users_file, data_root=data_root)

    users = load_users(users_file)
    admin = next(u for u in users if u["username"] == "admin")
    assert bcrypt.checkpw(b"new-secret", admin["password"].encode())
    assert not admin_password_setup_required(users_file, data_root=data_root)


def test_apply_admin_bootstrap_rewrites_default_admin_password(tmp_path, monkeypatch):
    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils

    path_utils._DATA_DIR = None
    path_utils._DATA_DIR_KEY = None
    path_utils._DATA_ROOT = None
    path_utils._DATA_ROOT_KEY = None

    save_admin_bootstrap(
        data_root=data_root,
        password_plaintext="bootstrap-secret",
        require_setup=False,
    )
    users_file = tmp_path / "users.txt"
    users_file.write_text("admin,pass,admin,\n", encoding="utf-8")

    assert apply_admin_bootstrap(users_file, data_root=data_root)

    users = load_users(users_file)
    admin = next(u for u in users if u["username"] == "admin")
    assert bcrypt.checkpw(b"bootstrap-secret", admin["password"].encode())
