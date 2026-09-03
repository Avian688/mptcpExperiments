#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys

from experimentKShortestPathsSupport import (
    SimulationConfig,
    default_cores,
    install_signal_handlers,
    run_simulation_configs,
    terminate_all_active_processes,
)
from generateExperimentKShortestPathsIni import EXPERIMENT_DIR, POLICIES, generate_ini


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate this MPTCP experiment's primary and K-path routing files"
    )
    parser.add_argument("--start-step", type=int, choices=(1, 2), default=1)
    parser.add_argument("--end-step", type=int, choices=(1, 2), default=2)
    parser.add_argument("--sim-time", type=float, default=300, help="Saved routing duration in seconds")
    parser.add_argument("--policies", nargs="+", choices=list(POLICIES), default=list(POLICIES))
    parser.add_argument(
        "--cores",
        type=int,
        default=default_cores(len(POLICIES)),
        help="Maximum simultaneous K-path generators (default: EXPERIMENT_CORES or up to 7 CPUs)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.environ.get("EXPERIMENT_RETRIES", "1")),
    )
    parser.add_argument(
        "--sim-timeout-seconds",
        type=float,
        default=float(os.environ.get("EXPERIMENT_SIM_TIMEOUT_SECONDS", str(8 * 60 * 60))),
        help="Wall-clock timeout per route-generation simulation (default: 8 hours)",
    )
    return parser.parse_args()


def main() -> int:
    install_signal_handlers()
    args = parse_args()
    if args.start_step > args.end_step:
        raise ValueError("--start-step must not exceed --end-step")

    generate_ini(args.sim_time)
    print(f"Route store: {EXPERIMENT_DIR / 'leoSaves'}")

    if args.start_step <= 1 <= args.end_step:
        print("Step 1/2: generating primary shortest-path routes")
        run_simulation_configs(
            [SimulationConfig("GenerateShortestPaths", require_vector=False)],
            "primary-routes",
            1,
            args.retries,
            args.sim_timeout_seconds,
        )

    if args.start_step <= 2 <= args.end_step:
        print("Step 2/2: generating K-shortest-path policy catalogs")
        configs = [
            SimulationConfig(f"Generate_{policy}", require_vector=False)
            for policy in args.policies
        ]
        run_simulation_configs(
            configs,
            "k-path-routes",
            args.cores,
            args.retries,
            args.sim_timeout_seconds,
        )
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
