"""
tests/test_run_concurrency.py
Verifies Windows file-locking race condition resistance:
Concurrent read operations (like those triggered by FastAPI endpoints)
must not cause PermissionError during safe_atomic_replace in save_run / start_run.
"""

import threading
import time
from pathlib import Path
from src.engine.run_manager import RunManager, safe_atomic_replace
from src.engine.models import RunStatus


def test_safe_atomic_replace_retry(tmp_path: Path):
    """Verifies safe_atomic_replace successfully replaces a file."""
    target = tmp_path / "target.txt"
    target.write_text("initial content", encoding="utf-8")
    
    tmp = tmp_path / "target.tmp"
    tmp.write_text("updated content", encoding="utf-8")
    
    safe_atomic_replace(tmp, target)
    assert target.read_text(encoding="utf-8") == "updated content"
    assert not tmp.exists()


def test_run_manager_concurrent_reads_and_writes(tmp_path: Path):
    """
    Simulates FastAPI Web UI behavior:
    10 threads constantly reading run_state.json while another thread repeatedly saves updates.
    Must execute with 0 exceptions or PermissionErrors.
    """
    rm = RunManager(base_runs_dir=tmp_path / "runs")
    run = rm.create_run(task="Concurrent stress test", dry_run=True)
    run_id = run.run_id

    errors = []
    stop_flag = threading.Event()

    def reader_worker():
        while not stop_flag.is_set():
            try:
                loaded = rm.load_run(run_id)
                assert loaded.run_id == run_id
            except Exception as e:
                errors.append(e)
            time.sleep(0.005)

    def writer_worker():
        for i in range(20):
            try:
                r = rm.load_run(run_id)
                r.metadata["iteration"] = i
                rm.save_run(r)
            except Exception as e:
                errors.append(e)
            time.sleep(0.01)

    # Spawn 8 concurrent reader threads (simulating multiple web requests)
    readers = [threading.Thread(target=reader_worker) for _ in range(8)]
    for t in readers:
        t.start()

    writer = threading.Thread(target=writer_worker)
    writer.start()

    writer.join(timeout=10.0)
    stop_flag.set()
    for t in readers:
        t.join(timeout=5.0)

    assert errors == [], f"Encountered concurrency errors: {errors}"
