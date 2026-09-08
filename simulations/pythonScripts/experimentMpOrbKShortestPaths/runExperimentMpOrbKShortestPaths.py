#!/usr/bin/env python3
"""Step 1: simulate; 2: export; 3: extract; 4: plot. No build is performed."""

import argparse
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from pathlib import Path

from generateExperimentMpOrbKShortestPathsIni import (
    SCRIPT_DIR, SIMULATIONS_DIR, SAMPLES_DIR, EXPERIMENT_DIR, INI_FILE, MANIFEST_FILE,
    SIM_TIME, ROUTE_STORE, CITY_COORDINATES, PAIR_DEFINITIONS, PATH_COUNT,
    MAX_RTT_SPREAD_MS, K_PATH_SNAPSHOT_SET, load_ground_stations, generate_ini,
)

RESULTS_DIR = EXPERIMENT_DIR / "results"
CSV_DIR = EXPERIMENT_DIR / "csvs"
LOG_DIR = SIMULATIONS_DIR / "logs" / "experimentMpOrbKShortestPaths"
PLOT_DIR = SIMULATIONS_DIR / "plots" / "experimentMpOrbKShortestPaths"
PROJECTS = ("inet4.5", "os3", "leosatellites", "tcpGoodputApplications", "tcpPaced",
            "cubic", "orbtcp", "mptcp", "mporb", "mptcpExperiments")
ACTIVE = set()
LOCK = threading.Lock()
STOP = threading.Event()


def tool_path(name):
    return os.environ.get(name.upper(), str(SAMPLES_DIR.parent / "bin" / name))


def route_directories():
    num_gs = len(CITY_COORDINATES) + len(load_ground_stations())
    base = (EXPERIMENT_DIR / ROUTE_STORE / f"1584_550_72_22_53_{num_gs}_ISL").resolve()
    # Same byte-wise FNV hash as computeKPathEndpointPairSetHash in LeoKPathSnapshot.cc.
    values = [len(PAIR_DEFINITIONS)]
    for _, _, _, source, destination in PAIR_DEFINITIONS:
        values.extend((1584 + num_gs + source, 1584 + num_gs + destination))
    hash_value = 1469598103934665603
    for value in values:
        for byte in value.to_bytes(4, "little"):
            hash_value = ((hash_value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    profile = (f"v3-edge-disjoint-mincost-k{PATH_COUNT}-rtt{MAX_RTT_SPREAD_MS}ms"
               f"-pairs-{hash_value:016x}")
    return base, base / "kpaths" / K_PATH_SNAPSHOT_SET / profile


def check_routes(sim_time):
    # LeoChannelConstructor: initial t=0, then 100ms + 1us, every 100ms.
    expected = {0, *range(100001, round(sim_time * 1_000_000), 100000)}
    inventory = []
    errors = []
    for directory in route_directories():
        present = {}
        for path in directory.glob("*.bin"):
            try:
                micros = int(Decimal(path.stem) * 1_000_000)
            except InvalidOperation:
                continue
            stat = path.stat()
            if stat.st_size > 0:
                present[micros] = path
                if micros in expected:
                    inventory.append((str(path), stat.st_size, stat.st_mtime_ns))
        missing = sorted(expected - present.keys())
        if missing:
            errors.append(f"{directory}: missing {len(missing)} snapshots; first t={missing[0] / 1e6:g}s")
    if errors:
        raise FileNotFoundError("Saved route coverage is incomplete:\n" + "\n".join(errors) +
            "\nUse experimentKShortestPaths/runExperimentKShortestPathsSaveFiles.py --policies EdgeDisjoint first.")
    print(f"Route coverage OK: {len(expected)} snapshots in each of the primary and edge-disjoint stores")
    return inventory


def simulation_command(config):
    ned_paths = [SIMULATIONS_DIR]
    ned_paths.extend(SAMPLES_DIR / p / "src" for p in PROJECTS)
    ned_paths.extend(SAMPLES_DIR / p / "simulations" for p in PROJECTS if p != "mptcpExperiments")
    command = [tool_path("opp_run"), "-r", "0", "-m", "-u", "Cmdenv", "-f", INI_FILE.name,
               "-c", config["config"], "-n", ":".join(str(p) for p in ned_paths if p.is_dir()),
               f"--image-path={SAMPLES_DIR / 'inet4.5' / 'images'}"]
    for project in PROJECTS:
        name = "INET" if project == "inet4.5" else project
        command.extend(("-l", str(SAMPLES_DIR / project / "src" / name)))
    return command


def result_path(config, suffix):
    return RESULTS_DIR / f'{config["config"]}-#0{suffix}'


def read_completion(config):
    path = result_path(config, ".complete.json")
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if data.get("config") != config:
        return None
    for suffix, saved_stat in data.get("outputs", {}).items():
        output = result_path(config, suffix)
        if not output.is_file():
            return None
        stat = output.stat()
        if [stat.st_size, stat.st_mtime_ns] != saved_stat:
            return None
    return data if set(data.get("outputs", {})) == {".vec", ".sca"} else None


def terminate(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def run_logged_command(command, log_path, timeout):
    if STOP.is_set():
        return False
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        log.write(json.dumps(command) + "\n")
        log.flush()
        with LOCK:
            if STOP.is_set():
                return False
            process = subprocess.Popen(command, cwd=EXPERIMENT_DIR, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            ACTIVE.add(process)
        try:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                terminate(process)
                log.write("\nTIMEOUT\n")
                return False
            log.write(f"\nExit code: {code}\n")
            return code == 0
        finally:
            with LOCK:
                ACTIVE.discard(process)


def run_config(config, fingerprint, resume, retries, timeout):
    completed = read_completion(config)
    if resume and completed and completed.get("fingerprint") == fingerprint:
        return True
    for attempt in range(retries + 1):
        if STOP.is_set():
            return False
        for suffix in (".vec", ".vci", ".sca", ".complete.json"):
            result_path(config, suffix).unlink(missing_ok=True)
        log = LOG_DIR / f'{config["config"]}.attempt{attempt + 1}.log'
        if not run_logged_command(simulation_command(config), log, timeout):
            continue
        outputs = {}
        for suffix in (".vec", ".sca"):
            path = result_path(config, suffix)
            if path.is_file() and path.stat().st_size > 0:
                stat = path.stat()
                outputs[suffix] = [stat.st_size, stat.st_mtime_ns]
        if len(outputs) == 2:
            result_path(config, ".complete.json").write_text(json.dumps(dict(
                config=config, fingerprint=fingerprint, outputs=outputs), indent=2) + "\n")
            return True
    return False


def simulation_fingerprint(route_inventory):
    libraries = []
    for project in PROJECTS:
        name = "INET" if project == "inet4.5" else project
        paths = [SAMPLES_DIR / project / "src" / f"lib{name}{ext}" for ext in (".so", ".dylib")]
        library = next((p for p in paths if p.is_file()), None)
        if library is None:
            raise FileNotFoundError(f"Build {project} before running: no library found in {paths[0].parent}")
        stat = library.stat()
        libraries.append((str(library), stat.st_size, stat.st_mtime_ns))
    payload = INI_FILE.read_bytes() + json.dumps([route_inventory, libraries], sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def run_simulations(configs, args):
    routes = check_routes(max(c["sim_time"] for c in configs))
    fingerprint = simulation_fingerprint(routes)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    executor = ThreadPoolExecutor(max_workers=args.cores)
    try:
        futures = {executor.submit(run_config, c, fingerprint, not args.rerun,
                                   args.retries, args.sim_timeout_seconds): c for c in configs}
        for index, future in enumerate(as_completed(futures), 1):
            config = futures[future]
            ok = future.result()
            print(f'{index}/{len(configs)} {"OK" if ok else "FAILED"} {config["config"]}', flush=True)
            if not ok:
                failures.append(config["config"])
    except BaseException:
        STOP.set()
        with LOCK:
            processes = list(ACTIVE)
        for process in processes:
            terminate(process)
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    if failures:
        raise RuntimeError(f"{len(failures)} failed runs; inspect {LOG_DIR}. Rerun to resume; failures are not plotted as zero.")


def export_results(configs):
    raw_dir = CSV_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for c in configs:
        if read_completion(c) is None:
            raise RuntimeError(f'No successful, unchanged result for {c["config"]}; run step 1 first')
        target = raw_dir / f'{c["config"]}.csv'
        command = [tool_path("opp_scavetool"), "export", "-F", "CSV-R", "-o", str(target),
                   str(result_path(c, ".vec")), str(result_path(c, ".sca"))]
        if not run_logged_command(command, LOG_DIR / f'{c["config"]}.export.log', 1800):
            raise RuntimeError(f'Export failed: {c["config"]}')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-step", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--end-step", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--sim-time", type=float, default=SIM_TIME)
    parser.add_argument("--cores", type=int, default=int(os.environ.get("EXPERIMENT_CORES", "2")))
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--sim-timeout-seconds", type=float, default=8 * 3600)
    parser.add_argument("--configs", nargs="+", help="Exact configuration names to run or process")
    parser.add_argument("--runs", nargs="+", type=int, choices=range(1, 6), help="Restrict run numbers (default all five)")
    parser.add_argument("--rerun", action="store_true", help="Rerun selected successful configurations")
    parser.add_argument("--dry-run", action="store_true", help="Generate/list selected configs without simulations or exports")
    parser.add_argument("--check-routes", action="store_true", help="Check saved coverage and exit; never simulates")
    args = parser.parse_args()
    if args.start_step > args.end_step or args.cores < 1 or args.retries < 0 or args.sim_timeout_seconds <= 0:
        parser.error("Invalid step range, core count, retry count, or timeout")
    return args


def main():
    args = parse_args()
    configs = generate_ini(args.sim_time) if args.start_step == 1 else json.loads(MANIFEST_FILE.read_text())
    if args.configs:
        unknown = set(args.configs) - {c["config"] for c in configs}
        if unknown:
            raise ValueError(f"Unknown configs: {sorted(unknown)}")
        configs = [c for c in configs if c["config"] in args.configs]
    if args.runs:
        configs = [c for c in configs if c["run"] in args.runs]
    if not configs:
        raise ValueError("No selected configurations")
    print(f"Selected {len(configs)} runs")
    if args.check_routes:
        check_routes(max(c["sim_time"] for c in configs))
        return
    if args.dry_run:
        for c in configs:
            print(c["config"])
        return
    for step, package in ((3, "numpy"), (4, "matplotlib")):
        if args.start_step <= step <= args.end_step and importlib.util.find_spec(package) is None:
            raise RuntimeError(f"Missing Python package {package}; activate a Python environment with NumPy and Matplotlib before running the pipeline")
    if args.start_step <= 1 <= args.end_step:
        run_simulations(configs, args)
    if args.start_step <= 2 <= args.end_step:
        export_results(configs)
    if args.start_step <= 3 <= args.end_step:
        for c in configs:
            completed = read_completion(c)
            raw = CSV_DIR / "raw" / f'{c["config"]}.csv'
            if completed is None or not raw.is_file() or raw.stat().st_mtime_ns < max(
                    stat[1] for stat in completed["outputs"].values()):
                raise RuntimeError(f'{c["config"]}: missing or stale export; run step 2 first')
        from extractSingleCsvFile import extract_results
        extract_results(configs)
    if args.start_step <= 4 <= args.end_step:
        from plotExperimentMpOrbKShortestPaths import plot_results
        plot_results(configs)


if __name__ == "__main__":
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
