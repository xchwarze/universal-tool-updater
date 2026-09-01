"""
Self-contained helper for run_pipeline.ps1's Ctrl+C / graceful-shutdown
scenario. Spawns the real UpdateManager.py as a child sharing this
process's console, waits --delay seconds, sends a real CTRL_C_EVENT to
the console process group, then waits (up to --timeout) for the child to
exit. Relays the child's combined stdout/stderr verbatim, followed by one
machine-parseable summary line the pipeline's Assert-* helpers regex
against.

Doing the whole signal dance in a dedicated Python process (instead of
from PowerShell directly) sidesteps two real Windows quirks:
  - GenerateConsoleCtrlEvent(CTRL_C_EVENT) broadcasts to the WHOLE console
    process group, including the sender, unless the sender explicitly
    ignores its own SIGINT first.
  - Spawning the target with CREATE_NEW_PROCESS_GROUP (a natural-looking
    choice to isolate it) actually PREVENTS CTRL_C_EVENT from ever
    reaching it at all - only CTRL_BREAK_EVENT (a different signal the
    app doesn't handle) can target an isolated process group.

Usage:
    python shutdown_scenario.py --scratch-dir <dir> --tools A B C [--delay 2.0] [--timeout 15]
"""

import argparse
import os
import pathlib
import signal
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scratch-dir', required=True)
    parser.add_argument('--delay', type=float, default=2.0)
    parser.add_argument('--timeout', type=float, default=15.0)
    parser.add_argument('--tools', nargs='+', required=True)
    args = parser.parse_args()

    # We are about to broadcast CTRL_C_EVENT to our own console process
    # group; without this we'd kill ourselves before we finish waiting on
    # the child.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    scratch = pathlib.Path(args.scratch_dir)
    mutex_path = scratch / 'mutex.lock'

    cmd = [sys.executable, 'UpdateManager.py', '--dry-run', '-dic', '-u', *args.tools]
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(scratch),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        # deliberately NOT using CREATE_NEW_PROCESS_GROUP - see module docstring
    )

    time.sleep(args.delay)
    sent_at = time.monotonic() - t0
    print(f'--- sending CTRL_C_EVENT at t={sent_at:.2f}s ---', flush=True)
    os.kill(proc.pid, signal.CTRL_C_EVENT)

    timed_out = False
    try:
        out, _ = proc.communicate(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        out, _ = proc.communicate()

    elapsed = time.monotonic() - t0
    print(out)

    mutex_cleaned = not mutex_path.exists()
    print(
        f'SHUTDOWN_HARNESS: elapsed={elapsed:.2f} exit_code={proc.returncode} '
        f'timed_out={timed_out} mutex_cleaned={mutex_cleaned}'
    )

    # mirror the child's exit code (0 == graceful) so this wrapper's own
    # ExitCode reads the same way every other scenario's does
    sys.exit(0 if (not timed_out and proc.returncode == 0) else 1)


if __name__ == '__main__':
    main()
