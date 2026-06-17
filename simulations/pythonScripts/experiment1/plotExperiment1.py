#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CONFIGS = [
    ("cubic", "default", "CUBIC default"),
    ("cubic", "lowestRtt", "CUBIC lowestRTT"),
    ("cubic", "directPull", "CUBIC directPull"),
    ("mporb", "default", "MPORB default"),
    ("mporb", "lowestRtt", "MPORB lowestRTT"),
    ("mporb", "directPull", "MPORB directPull"),
]


@dataclass
class SeriesBundle:
    protocol: str
    scheduler: str
    label: str
    app_goodput: pd.Series
    subflows: list[pd.Series]
    hol_blocked: pd.Series | None
    dsn_gap: pd.Series | None


def read_series(path: Path, column: str) -> pd.Series | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "time" not in df.columns or column not in df.columns:
        return None
    series = pd.Series(df[column].to_numpy(dtype=float), index=df["time"].to_numpy(dtype=float))
    return series[~series.index.duplicated(keep="last")].sort_index()


def resample_to_grid(series: pd.Series, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).interpolate(method="index").reindex(grid).fillna(0)


def sample_hold_to_grid(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def read_connection_series(run_root: Path, metric: str) -> pd.Series | None:
    paths = sorted(run_root.glob(f"schedulernegativetwopaths.server[0].tcp.conn-*/{metric}.csv"))
    candidates = [
        series
        for path in paths
        if (series := read_series(path, metric)) is not None and not series.empty
    ]
    return max(candidates, key=len) if candidates else None


def load_bundle(csv_root: Path, protocol: str, scheduler: str, label: str, run: int) -> SeriesBundle | None:
    run_root = csv_root / protocol / scheduler / f"run{run}"
    app_path = run_root / "schedulernegativetwopaths.server[0].app[0]" / "goodput.csv"
    app_goodput = read_series(app_path, "goodput")
    if app_goodput is None:
        print(f"warning: missing app goodput for {label}: {app_path}")
        return None

    throughput_paths = sorted(run_root.glob("schedulernegativetwopaths.server[0].tcp.conn-*/throughput.csv"))
    subflows = [series for path in throughput_paths if (series := read_series(path, "throughput")) is not None]

    # Keep the two active data-carrying subflows if listener/meta artifacts are present.
    subflows = sorted(subflows, key=lambda s: float(s.mean()) if not s.empty else 0.0, reverse=True)[:2]
    hol_blocked = read_connection_series(run_root, "holBlockedBytes")
    dsn_gap = read_connection_series(run_root, "metaDsnGapBytes")
    return SeriesBundle(protocol, scheduler, label, app_goodput, subflows, hol_blocked, dsn_gap)


def common_grid(bundles: list[SeriesBundle]) -> np.ndarray:
    starts = []
    ends = []
    for bundle in bundles:
        all_series = [bundle.app_goodput, *bundle.subflows, bundle.hol_blocked, bundle.dsn_gap]
        starts.extend(float(s.index.min()) for s in all_series if s is not None and not s.empty)
        ends.extend(float(s.index.max()) for s in all_series if s is not None and not s.empty)
    if not starts or not ends:
        return np.asarray([])
    return np.arange(max(min(starts), 0.0), max(ends) + 0.5, 0.5)


def aggregate_subflows(bundle: SeriesBundle, grid: np.ndarray) -> pd.Series:
    total = pd.Series(np.zeros_like(grid), index=grid)
    for series in bundle.subflows:
        total = total.add(resample_to_grid(series, grid), fill_value=0)
    return total


def final_window_mean(series: pd.Series, start_time: float) -> float:
    window = series[series.index >= start_time]
    if window.empty:
        window = series
    return float(window.mean()) if not window.empty else 0.0


def save_aggregate_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 5))
    for bundle in bundles:
        app = resample_to_grid(bundle.app_goodput, grid) / 1e6
        plt.plot(grid, app, label=bundle.label)
    plt.xlabel("Time (s)")
    plt.ylabel("Application goodput (Mbps)")
    plt.title("Aggregate Application Goodput")
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "aggregate_goodput_timeseries.pdf")
    plt.close()


def save_subflow_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(3, 2, figsize=(11, 8), sharex=True, sharey=True)
    for ax, bundle in zip(axes.flat, bundles):
        for index, series in enumerate(bundle.subflows, start=1):
            ax.plot(grid, resample_to_grid(series, grid) / 1e6, label=f"subflow {index}")
        ax.set_title(bundle.label)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Subflow throughput (Mbps)")
    fig.suptitle("Per-Subflow Goodput Proxy")
    fig.tight_layout()
    fig.savefig(out_dir / "per_subflow_goodput_timeseries.pdf")
    plt.close(fig)


def save_hol_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 5))
    for bundle in bundles:
        app = resample_to_grid(bundle.app_goodput, grid)
        subflow_total = aggregate_subflows(bundle, grid)
        hol_gap = (subflow_total - app).clip(lower=0) / 1e6
        plt.plot(grid, hol_gap, label=bundle.label)
    plt.xlabel("Time (s)")
    plt.ylabel("Subflow receive throughput - app goodput (Mbps)")
    plt.title("HoL / Reordering Delivery Gap Proxy")
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "hol_gap_timeseries.pdf")
    plt.close()


def save_hol_blocked_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 5))
    for bundle in bundles:
        plt.plot(grid, sample_hold_to_grid(bundle.hol_blocked, grid) / 1024, label=bundle.label)
    plt.xlabel("Time (s)")
    plt.ylabel("Buffered out-of-order data (KiB)")
    plt.title("Receiver HoL-Blocked Bytes")
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "hol_blocked_bytes_timeseries.pdf")
    plt.close()


def save_dsn_gap_plot(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 5))
    for bundle in bundles:
        plt.plot(grid, sample_hold_to_grid(bundle.dsn_gap, grid) / 1024, label=bundle.label)
    plt.xlabel("Time (s)")
    plt.ylabel("Arrived DSN - expected DSN (KiB)")
    plt.title("Receiver DSN Gap")
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "dsn_gap_timeseries.pdf")
    plt.close()


def save_summary(bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path, final_window: float) -> None:
    rows = []
    window_start = max(float(grid.max()) - final_window, float(grid.min())) if len(grid) else 0.0
    for bundle in bundles:
        app = resample_to_grid(bundle.app_goodput, grid)
        subflow_total = aggregate_subflows(bundle, grid)
        hol_gap = (subflow_total - app).clip(lower=0)
        row = {
            "protocol": bundle.protocol,
            "scheduler": bundle.scheduler,
            "app_goodput_mbps": final_window_mean(app / 1e6, window_start),
            "subflow_sum_mbps": final_window_mean(subflow_total / 1e6, window_start),
            "hol_gap_mbps": final_window_mean(hol_gap / 1e6, window_start),
            "hol_blocked_kib": final_window_mean(sample_hold_to_grid(bundle.hol_blocked, grid) / 1024, window_start),
            "dsn_gap_kib": final_window_mean(sample_hold_to_grid(bundle.dsn_gap, grid) / 1024, window_start),
        }
        for index, series in enumerate(bundle.subflows, start=1):
            row[f"subflow_{index}_mbps"] = final_window_mean(resample_to_grid(series, grid) / 1e6, window_start)
        rows.append(row)

    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "summary_final_window.csv", index=False)

    labels = [f"{row.protocol}\n{row.scheduler}" for row in summary.itertuples()]
    x = np.arange(len(summary))
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    axes[0].bar(x, summary["app_goodput_mbps"])
    axes[0].set_title("Final-Window App Goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].set_xticks(x, labels, rotation=30, ha="right")
    axes[0].grid(True, axis="y", alpha=0.3)

    axes[1].bar(x, summary["hol_gap_mbps"])
    axes[1].set_title("Final-Window HoL Gap Proxy")
    axes[1].set_ylabel("Mbps")
    axes[1].set_xticks(x, labels, rotation=30, ha="right")
    axes[1].grid(True, axis="y", alpha=0.3)

    axes[2].bar(x, summary["hol_blocked_kib"])
    axes[2].set_title("Final-Window HoL-Blocked Data")
    axes[2].set_ylabel("KiB")
    axes[2].set_xticks(x, labels, rotation=30, ha="right")
    axes[2].grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "summary_final_window.pdf")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 1.")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--final-window", type=float, default=60.0)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    experiment_root = sim_root / "experiments" / "experiment1"
    csv_root = experiment_root / "csvs"
    out_dir = sim_root / "plots" / "experiment1"
    out_dir.mkdir(parents=True, exist_ok=True)

    bundles = [
        bundle
        for protocol, scheduler, label in CONFIGS
        if (bundle := load_bundle(csv_root, protocol, scheduler, label, args.run)) is not None
    ]
    if not bundles:
        print(f"no extracted CSV data found under {csv_root}")
        return 1

    grid = common_grid(bundles)
    if len(grid) == 0:
        print("no usable timeseries data found")
        return 1

    save_aggregate_plot(bundles, grid, out_dir)
    save_subflow_plot(bundles, grid, out_dir)
    save_hol_plot(bundles, grid, out_dir)
    save_hol_blocked_plot(bundles, grid, out_dir)
    save_dsn_gap_plot(bundles, grid, out_dir)
    save_summary(bundles, grid, out_dir, args.final_window)
    print(f"wrote plots and summary under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
