"""Acquire only January–September 2026 development derivatives, never holdout."""
from pathlib import Path
from datetime import date
import json
import derivatives_dataset as source

if __name__=="__main__":
    source.START=date(2026,1,1)
    source.END=date(2026,10,1)
    source.main()
    path=Path("lab-derivatives/manifest.json")
    if path.exists():
        m=json.loads(path.read_text())
        m["period"]="2026-01-01 to 2026-10-01 exclusive; development extension only"
        assert all(f["start"]>="2026-01-01" and f["end_exclusive"]<="2026-10-01" for f in m["files"])
        path.write_text(json.dumps(m,indent=2))
        if any(v["verified"]!=v["files"] for v in m["summary"].values()):
            raise SystemExit("2026 derivative archives incomplete")
