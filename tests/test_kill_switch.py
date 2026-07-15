"""Kill switch logic tested against a throwaway temp state dir, not the real one."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from broker import kill_switch


def run():
    tmp_dir = Path(tempfile.mkdtemp())
    kill_switch.STATE_DIR = tmp_dir
    kill_switch.TRIPPED_FILE = tmp_dir / "kill_switch_tripped.json"

    try:
        baseline = kill_switch.get_baseline()
        assert baseline > 0

        assert not kill_switch.check_and_trip(baseline * 0.5, baseline), "50% drawdown should not trip a 70% kill switch"
        assert not kill_switch.is_tripped()

        assert kill_switch.check_and_trip(baseline * 0.29, baseline), "equity at/below 30% of baseline should trip"
        assert kill_switch.is_tripped()

        assert kill_switch.check_and_trip(baseline * 0.999, baseline), "should remain tripped until manually reset"

        kill_switch.reset()
        assert not kill_switch.is_tripped()

        print("kill_switch logic: OK")
    finally:
        shutil.rmtree(tmp_dir)


if __name__ == "__main__":
    run()
