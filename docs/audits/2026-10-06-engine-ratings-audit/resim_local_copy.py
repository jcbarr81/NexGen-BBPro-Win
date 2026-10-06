"""Simulate N days of a LOCAL COPY of a league with the current engine."""
import os, sys, time, json
root, league, days = sys.argv[1], sys.argv[2], int(sys.argv[3])
os.environ["NEXGEN_DATA_ROOT"] = root
for k in ("NEXGEN_DISCORD_WEBHOOK_URL", "NEXGEN_WORKING_COPY", "SENDGRID_API_KEY"):
    os.environ.pop(k, None)
sys.path.insert(0, ".")
from utils import path_utils
path_utils.set_request_league(league)
d = path_utils.get_data_dir()
from pathlib import Path
assert Path(d).resolve().is_relative_to(Path(root).resolve()), d
from api.routers import season as S
t0 = time.time()
manager, simulator, draft_date = S._build_manager_and_simulator()
res = S._simulate_n(manager, simulator, days, draft_date=draft_date)
print(json.dumps({k: res.get(k) for k in list(res)[:12]}, default=str)[:800])
print(f"simulated {days} days in {time.time()-t0:.1f}s; data dir {d}")
