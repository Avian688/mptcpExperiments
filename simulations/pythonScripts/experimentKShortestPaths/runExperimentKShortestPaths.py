#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import sys

from experimentKShortestPathsSupport import (
    EXPERIMENT_DIR,
    INI_FILE,
    RESULTS_DIR,
    SIMULATIONS_DIR,
    SimulationConfig,
    default_cores,
    install_signal_handlers,
    run_simulation_configs,
    terminate_all_active_processes,
)
from generateExperimentKShortestPathsIni import POLICIES, generate_ini


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and analyze the MPTCP K-shortest-path RTT experiment"
    )
    parser.add_argument("--start-step", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--end-step", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--policies", nargs="+", choices=list(POLICIES), default=list(POLICIES))
    parser.add_argument(
        "--cores",
        type=int,
        default=default_cores(len(POLICIES)),
        help="Maximum simultaneous policy runs (default: EXPERIMENT_CORES or up to 7 CPUs)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.environ.get("EXPERIMENT_RETRIES", "1")),
    )
    parser.add_argument(
        "--sim-timeout-seconds",
        type=float,
        default=float(os.environ.get("EXPERIMENT_SIM_TIMEOUT_SECONDS", str(2.5 * 60 * 60))),
    )
    parser.add_argument("--sim-time", type=float, default=300, help="Simulation duration in seconds")
    parser.add_argument("--resume", action="store_true", help="Keep completed ping simulations")
    parser.add_argument("--clean", action="store_true", help="Remove existing results, CSVs, and plots")
    parser.add_argument("--skip-export", action="store_true", help="Use existing CSV-R exports in step 3")
    return parser.parse_args()


def enabled(step: int, args: argparse.Namespace) -> bool:
    return args.start_step <= step <= args.end_step


def main() -> int:
    install_signal_handlers()
    args = parse_args()
    if args.start_step > args.end_step:
        raise ValueError("--start-step must not exceed --end-step")

    if args.clean:
        shutil.rmtree(RESULTS_DIR, ignore_errors=True)
        shutil.rmtree(EXPERIMENT_DIR / "csvs", ignore_errors=True)
        shutil.rmtree(SIMULATIONS_DIR / "plots" / "experimentKShortestPaths", ignore_errors=True)

    if enabled(1, args):
        print("Step 1/3: generating the MPTCP experiment INI")
        generate_ini(args.sim_time)
    elif not INI_FILE.is_file():
        raise FileNotFoundError(f"Missing {INI_FILE}; run step 1 first")

    if enabled(2, args):
        print("Step 2/3: running ping probes")
        configs = [SimulationConfig(f"Ping_{policy}") for policy in args.policies]
        run_simulation_configs(
            configs,
            "pings",
            args.cores,
            args.retries,
            args.sim_timeout_seconds,
            args.resume,
        )

    if enabled(3, args):
        print("Step 3/3: extracting and plotting average RTT results")
        from analyzeExperimentKShortestPaths import analyze

        analyze(args.policies, args.skip_export)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        terminate_all_active_processes()
        print("Cancelled; active simulation process groups were stopped.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        terminate_all_active_processes()
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
