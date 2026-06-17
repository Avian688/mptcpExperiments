#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

CONFIGS = [
    ("CubicUncoupled", "cubic"),
    ("MpOrbUncoupled", "mporb"),
]


@dataclass(frozen=True)
class Entry:
    config: str
    protocol: str
    run: int = 1


SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
PROJECT_ROOT = SIM_ROOT.parent
SAMPLES_ROOT = PROJECT_ROOT.parent
REPO_ROOT = SAMPLES_ROOT.parent
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experiment2"
RESULTS_DIR = EXPERIMENT_DIR / "results"
LOG_DIR = SIM_ROOT / "logs" / "experiment2"
ACTIVE_PROCESSES: set[subprocess.Popen] = set()
ACTIVE_PROCESSES_LOCK = threading.Lock()


def tool_path(name: str) -> str:
    env_name = name.upper()
    if os.environ.get(env_name):
        return os.environ[env_name]
    bundled = REPO_ROOT / "bin" / name
    if bundled.exists():
        return str(bundled)
    return name


def parse_args() -> argparse.Namespace:
    default_cores = max(1, int(os.environ.get("EXPERIMENT_CORES", str(os.cpu_count() or 1))))
    parser = argparse.ArgumentParser(description="Run mptcpExperiments experiment 2.")
    parser.add_argument("--cores", type=int, default=default_cores)
    parser.add_argument("--retries", type=int, default=int(os.environ.get("EXPERIMENT_RETRIES", "3")))
    parser.add_argument(
        "--sim-timeout-seconds",
        type=float,
        default=float(os.environ.get("EXPERIMENT_SIM_TIMEOUT_SECONDS", str(2.5 * 60 * 60))),
    )
    parser.add_argument("--sim-time-limit", help="Optional OMNeT++ sim-time-limit override, e.g. 5s.")
    parser.add_argument("--start-step", type=int, default=1, help="1=simulate, 2=export, 3=extract, 4=plot")
    parser.add_argument("--end-step", type=int, default=4)
    parser.add_argument("--resume", action="store_true", help="Skip simulations with existing vector/scalar output.")
    parser.add_argument("--clean", action="store_true", help="Remove experiment2 results/csvs/plots before running.")
    parser.add_argument("--configs", nargs="*", default=[entry[0] for entry in CONFIGS])
    return parser.parse_args()


def enabled(step: int, args: argparse.Namespace) -> bool:
    return args.start_step <= step <= args.end_step


def entries(args: argparse.Namespace) -> list[Entry]:
    wanted = set(args.configs)
    return [Entry(*item) for item in CONFIGS if item[0] in wanted]


def common_ned_path() -> str:
    paths = [
        SIM_ROOT,
        PROJECT_ROOT / "src",
        SAMPLES_ROOT / "mptcp" / "simulations",
        SAMPLES_ROOT / "mptcp" / "src",
        SAMPLES_ROOT / "mporb" / "simulations",
        SAMPLES_ROOT / "mporb" / "src",
        SAMPLES_ROOT / "orbtcp" / "simulations",
        SAMPLES_ROOT / "orbtcp" / "src",
        SAMPLES_ROOT / "cubic" / "simulations",
        SAMPLES_ROOT / "cubic" / "src",
        SAMPLES_ROOT / "tcpPaced" / "simulations",
        SAMPLES_ROOT / "tcpPaced" / "src",
        SAMPLES_ROOT / "tcpGoodputApplications" / "simulations",
        SAMPLES_ROOT / "tcpGoodputApplications" / "src",
        SAMPLES_ROOT / "inet4.5" / "examples",
        SAMPLES_ROOT / "inet4.5" / "showcases",
        SAMPLES_ROOT / "inet4.5" / "src",
        SAMPLES_ROOT / "inet4.5" / "tests" / "validation",
        SAMPLES_ROOT / "inet4.5" / "tests" / "networks",
        SAMPLES_ROOT / "inet4.5" / "tutorials",
    ]
    return ":".join(str(path) for path in paths)


def load_libs() -> list[str]:
    return [
        str(SAMPLES_ROOT / "inet4.5" / "src" / "INET"),
        str(SAMPLES_ROOT / "tcpGoodputApplications" / "src" / "tcpGoodputApplications"),
        str(SAMPLES_ROOT / "tcpPaced" / "src" / "tcpPaced"),
        str(SAMPLES_ROOT / "cubic" / "src" / "cubic"),
        str(SAMPLES_ROOT / "orbtcp" / "src" / "orbtcp"),
        str(SAMPLES_ROOT / "mptcp" / "src" / "mptcp"),
        str(SAMPLES_ROOT / "mporb" / "src" / "mporb"),
        str(PROJECT_ROOT / "src" / "mptcpExperiments"),
    ]


def expected_vec(entry: Entry) -> Path:
    return RESULTS_DIR / f"{entry.config}-#0.vec"


def expected_sca(entry: Entry) -> Path:
    return RESULTS_DIR / f"{entry.config}-#0.sca"


def expected_export(entry: Entry) -> Path:
    return RESULTS_DIR / f"{entry.config}.csv"


def clean_entry(entry: Entry) -> None:
    for suffix in ("-#0.vec", "-#0.vci", "-#0.sca", ".csv"):
        (RESULTS_DIR / f"{entry.config}{suffix}").unlink(missing_ok=True)


def simulation_command(entry: Entry, args: argparse.Namespace) -> list[str]:
    cmd = [
        tool_path("opp_run"),
        "-r",
        "0",
        "-m",
        "-u",
        "Cmdenv",
        "-f",
        "experiment2.ini",
        "-c",
        entry.config,
        "-n",
        common_ned_path(),
        f"--image-path={SAMPLES_ROOT / 'inet4.5' / 'images'}",
    ]
    for lib in load_libs():
        cmd.extend(["-l", lib])
    if args.sim_time_limit:
        cmd.append(f"--sim-time-limit={args.sim_time_limit}")
    return cmd


def terminate_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            process.kill()
        process.wait()


def register_process(process: subprocess.Popen) -> None:
    with ACTIVE_PROCESSES_LOCK:
        ACTIVE_PROCESSES.add(process)


def unregister_process(process: subprocess.Popen) -> None:
    with ACTIVE_PROCESSES_LOCK:
        ACTIVE_PROCESSES.discard(process)


def terminate_all_active_processes() -> None:
    with ACTIVE_PROCESSES_LOCK:
        processes = list(ACTIVE_PROCESSES)
    for process in processes:
        terminate_process_group(process)


def handle_termination_signal(signum, _frame) -> None:
    print(f"\nReceived signal {signum}; cancelling experiment runner...", file=sys.stderr)
    raise KeyboardInterrupt


def run_logged_command(
    command: list[str],
    cwd: Path,
    log_path: Path,
    timeout_seconds: float | None = None,
) -> tuple[int, bool]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        register_process(process)
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_group(process)
            return_code = process.returncode if process.returncode is not None else 124
        except BaseException:
            terminate_process_group(process)
            elapsed = time.monotonic() - started
            log.write(f"\nInterrupted after {elapsed:.2f} seconds; terminated child process group\n")
            log.flush()
            raise
        finally:
            unregister_process(process)

        elapsed = time.monotonic() - started
        if timed_out:
            log.write(f"\nTimed out after {elapsed:.2f} seconds\n")
        log.write(f"\nExit code: {return_code}\n")
        log.write(f"Elapsed seconds: {elapsed:.2f}\n")
    return return_code, timed_out


def reached_time_limit_before_cleanup(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "Simulation time limit reached" in text and "Calling finish() at end of Run" in text


def run_simulation(entry: Entry, args: argparse.Namespace) -> tuple[Entry, bool, int, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.resume and expected_vec(entry).exists() and expected_sca(entry).exists():
        return entry, True, 0, Path()
    clean_entry(entry)

    log_path = LOG_DIR / "simulations" / f"{entry.config}.log"
    command = simulation_command(entry, args)
    return_code, timed_out = run_logged_command(command, EXPERIMENT_DIR, log_path, args.sim_timeout_seconds)
    has_results = expected_vec(entry).exists() and expected_sca(entry).exists()
    ok = has_results and (return_code == 0 or reached_time_limit_before_cleanup(log_path))
    return entry, ok, return_code, log_path


def export_csv(entry: Entry) -> tuple[Entry, bool, int, Path]:
    csv_path = expected_export(entry)
    csv_path.unlink(missing_ok=True)
    log_path = LOG_DIR / "scavetool" / f"{entry.config}.log"
    command = [
        tool_path("opp_scavetool"),
        "export",
        "-o",
        f"results/{entry.config}.csv",
        "-F",
        "CSV-R",
        f"results/{entry.config}-#0.vec",
    ]
    return_code, _timed_out = run_logged_command(command, EXPERIMENT_DIR, log_path)
    return entry, return_code == 0 and csv_path.exists(), return_code, log_path


def extract_csv(entry: Entry) -> tuple[Entry, bool, int, Path]:
    out_root = EXPERIMENT_DIR / "csvs" / entry.protocol / f"run{entry.run}"
    shutil.rmtree(out_root, ignore_errors=True)
    log_path = LOG_DIR / "extract" / f"{entry.config}.log"
    command = [
        sys.executable,
        str(SCRIPT_DIR / "extractSingleCsvFile.py"),
        str(expected_export(entry)),
        entry.protocol,
        str(entry.run),
    ]
    return_code, _timed_out = run_logged_command(command, SCRIPT_DIR, log_path)
    ok = return_code == 0 and out_root.is_dir() and any(out_root.rglob("*.csv"))
    return entry, ok, return_code, log_path


def run_parallel(label: str, work, work_entries: list[Entry], args: argparse.Namespace) -> None:
    pending = list(work_entries)
    attempts = args.retries + 1
    failure_lines: list[str] = []
    for attempt in range(1, attempts + 1):
        if not pending:
            return

        print(f"\n{label}: {len(pending)} task(s), attempt {attempt}/{attempts}, {args.cores} core(s)")
        failures: list[Entry] = []
        failure_lines = []
        executor = ThreadPoolExecutor(max_workers=args.cores)
        futures = {}
        interrupted = False
        try:
            futures = {executor.submit(work, entry): entry for entry in pending}
            for future in as_completed(futures):
                entry, ok, code, log_path = future.result()
                if ok:
                    print(f"  ok: {entry.config}")
                else:
                    failures.append(entry)
                    line = f"{entry.config} (exit {code}, log: {log_path})"
                    failure_lines.append(line)
                    print(f"  failed: {line}")
        except KeyboardInterrupt:
            interrupted = True
            for future in futures:
                future.cancel()
            terminate_all_active_processes()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            if not interrupted:
                executor.shutdown(wait=True)

        pending = failures
        if pending and attempt < attempts:
            print(f"\nRetrying {len(pending)} failed/missing task(s).\n")

    if pending:
        raise RuntimeError(label + " failed:\n  " + "\n  ".join(failure_lines))


def main() -> int:
    signal.signal(signal.SIGTERM, handle_termination_signal)
    args = parse_args()
    try:
        selected = entries(args)
        if not selected:
            print("no matching configs selected")
            return 1

        if args.clean:
            shutil.rmtree(RESULTS_DIR, ignore_errors=True)
            shutil.rmtree(EXPERIMENT_DIR / "csvs", ignore_errors=True)
            shutil.rmtree(SIM_ROOT / "plots" / "experiment2", ignore_errors=True)

        if enabled(1, args):
            run_parallel("Running simulations", lambda entry: run_simulation(entry, args), selected, args)
        if enabled(2, args):
            run_parallel("Exporting vectors", export_csv, selected, args)
        if enabled(3, args):
            run_parallel("Extracting metric CSVs", extract_csv, selected, args)
        if enabled(4, args):
            command = [sys.executable, str(SCRIPT_DIR / "plotExperiment2.py")]
            result = subprocess.run(command, cwd=str(SCRIPT_DIR))
            if result.returncode != 0:
                return result.returncode
    except KeyboardInterrupt:
        print("\nCancelled; terminating active child processes.", file=sys.stderr)
        terminate_all_active_processes()
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
