"""Run the model slots WITHOUT systemd — plain detached background processes.

    python -m abstract_hugpy.managers.serve.slots_launch start
    python -m abstract_hugpy.managers.serve.slots_launch status
    python -m abstract_hugpy.managers.serve.slots_launch stop
    python -m abstract_hugpy.managers.serve.slots_launch restart

Spawns ``SLOT_COUNT`` slot supervisors (each ``python -m
abstract_hugpy.managers.serve.slot_agent``), each detached from the terminal
(``start_new_session``) so they keep running after you log out — no systemd, no
sudo, no unit files. pid/log files live under ``$SLOT_STATE_DIR`` (default
``~/.abstract_hugpy/slots``).

Because each slot is its own session leader, stopping it kills the whole process
group — i.e. the slot supervisor AND its ``llama-server`` child.

Honoured env (forwarded to every slot): SLOT_COUNT, SLOT_PORT_BASE,
SLOT_ADVERTISE, MAIN_GPU, LLAMA_SERVER_BIN, plus anything else already exported.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def _slot_count() -> int:
    try:
        return max(1, int(os.environ.get("SLOT_COUNT", "2")))
    except ValueError:
        return 2


def _state_dir() -> str:
    return os.environ.get("SLOT_STATE_DIR") or os.path.expanduser("~/.abstract_hugpy/slots")


def _pid_path(slot_id: int) -> str:
    return os.path.join(_state_dir(), f"slot-{slot_id}.pid")


def _log_path(slot_id: int) -> str:
    return os.path.join(_state_dir(), f"slot-{slot_id}.log")


def _read_pid(slot_id: int) -> int | None:
    try:
        with open(_pid_path(slot_id), "r", encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _port_base() -> int:
    try:
        return int(os.environ.get("SLOT_PORT_BASE", "8101"))
    except ValueError:
        return 8101


def start() -> int:
    os.makedirs(_state_dir(), exist_ok=True)
    base = _port_base()
    for slot_id in range(1, _slot_count() + 1):
        existing = _read_pid(slot_id)
        if _alive(existing):
            print(f"slot {slot_id}: already running (pid {existing}, port {base + slot_id - 1})")
            continue

        env = dict(os.environ)
        env["SLOT_ID"] = str(slot_id)
        env.setdefault("SLOT_PORT_BASE", str(base))

        log = open(_log_path(slot_id), "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "abstract_hugpy.managers.serve.slot_agent"],
            env=env,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,   # detach: own session/group, survives logout
        )
        with open(_pid_path(slot_id), "w", encoding="utf-8") as fh:
            fh.write(str(proc.pid))
        print(f"slot {slot_id}: started (pid {proc.pid}, port {base + slot_id - 1}, "
              f"log {_log_path(slot_id)})")
    return 0


def stop() -> int:
    for slot_id in range(1, _slot_count() + 1):
        pid = _read_pid(slot_id)
        if not _alive(pid):
            print(f"slot {slot_id}: not running")
            _safe_unlink(_pid_path(slot_id))
            continue
        # Kill the whole group (supervisor + its llama-server child).
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(30):
            if not _alive(pid):
                break
            time.sleep(0.5)
        if _alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
        print(f"slot {slot_id}: stopped (pid {pid})")
        _safe_unlink(_pid_path(slot_id))
    return 0


def status() -> int:
    base = _port_base()
    # Liveness from pidfiles…
    for slot_id in range(1, _slot_count() + 1):
        pid = _read_pid(slot_id)
        state = f"running (pid {pid})" if _alive(pid) else "stopped"
        print(f"slot {slot_id} [:{base + slot_id - 1}] {state}")
    # …and what each is actually serving, via the pool.
    try:
        from .slots import SlotPool
        for row in SlotPool().overview():
            mk = row.get("model_key") or "(idle)"
            free = row.get("free_vram_bytes")
            free_s = f"{free / 2**30:.1f} GiB free" if free else "VRAM ?"
            err = row.get("error")
            print(f"  {row.get('_control')}: {mk}  {free_s}"
                  + (f"  [{err}]" if err else ""))
    except Exception as exc:  # pragma: no cover
        print(f"  (pool status unavailable: {exc})")
    return 0


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "start":
        return start()
    if cmd == "stop":
        return stop()
    if cmd == "restart":
        stop()
        return start()
    if cmd == "status":
        return status()
    print(f"usage: {sys.argv[0]} [start|stop|restart|status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
