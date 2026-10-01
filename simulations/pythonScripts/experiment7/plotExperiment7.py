#!/usr/bin/env python3
"""Parking-lot goodput ratio versus RTT, and per-run transport/link diagnostics."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from plotAlphaValidation import read, load, subflows, save, mean_variance
from parkingLot import (SIM_ROOT, PROTOCOLS, RTTS_MS, RUNS, CONNECTIONS, CLIENTS,
                        SERVERS, QUEUES, INTERVAL, CAPACITY_MBPS, configurations,
                        prefix, slug, duration, measurement_start, spine_start)

COLORS = ('#2878b5', '#e47722', '#31945b', '#9467bd')


def sample(series, grid, rate=False):
    """Interval-end periodic rates; sample-hold states. Never extend a rate tail.

    Grid points are one-second bin centres. A missing rate sample remains NaN,
    rather than joining a gap or treating absent output as zero goodput.
    """
    times, values = series
    out = np.full(grid.shape, np.nan)
    if not len(times):
        return out
    if rate:
        indices = np.searchsorted(times, grid, side='left')
        valid = indices < len(times)
        valid[valid] &= times[indices[valid]] - grid[valid] <= INTERVAL + 1e-8
    else:
        indices = np.searchsorted(times, grid, side='right') - 1
        valid = indices >= 0
    out[valid] = values[indices[valid]]
    return out


def goodput_curves(root, grid, rtt, run):
    curves = []
    for i, server in enumerate(SERVERS):
        traces = load(root, f'{server}.app[0]', 'goodput')
        curve = (np.sum([sample(s, grid, True) for _, s in traces], axis=0) / 1e6
                 if traces else np.full(grid.shape, np.nan))
        # Known scheduled absence before a connection starts is a real zero.
        if traces:
            start = spine_start(rtt, run) if i == 0 else 0
            curve[grid < start] = 0
        curves.append(curve)
    return np.array(curves)


def fairness_row(goodput, grid, rtt):
    window = grid >= measurement_start(rtt)
    common = window & np.all(np.isfinite(goodput), axis=0)
    coverage = float(common.sum() / window.sum())
    result = dict(window_start_s=measurement_start(rtt), window_end_s=duration(rtt),
                  coverage_fraction=coverage)
    # Periodic timers usually do not emit exactly at the simulation limit.
    # Exempt only the final potentially unrecorded interval, not internal gaps.
    # Otherwise the 20-ms case (10-s window) would fail a 95% rule solely
    # because its last one-second sample falls after the simulation ends.
    required = window & (grid < duration(rtt) - INTERVAL)
    usable = bool(common.any() and common[required].mean() >= 0.95)
    values = goodput[:, common]
    for i, name in enumerate(('spine', 'rib1', 'rib2', 'rib3')):
        result[f'{name}_goodput_mbps'] = float(values[i].mean()) if usable else np.nan
    largest_rib = values[1:].max(axis=0) if values.size else np.array([])
    max_rate = np.maximum(values[0], largest_rib) if values.size else np.array([])
    valid_ratio = max_rate > 0
    result['goodput_ratio'] = (float(np.mean(np.minimum(values[0], largest_rib)[valid_ratio]
                                                    / max_rate[valid_ratio]))
                               if usable and valid_ratio.any() else np.nan)
    # Keep direction in the CSV: the legacy bounded ratio hides which side wins.
    valid_rib = largest_rib > 0
    result['spine_over_max_rib'] = (float(np.mean(values[0, valid_rib] / largest_rib[valid_rib]))
                                  if usable and valid_rib.any() else np.nan)
    return result


def decorate(ax, rtt, ylabel):
    ax.set(xlim=(0, duration(rtt)), xlabel='Time (s)', ylabel=ylabel)
    ax.axvspan(measurement_start(rtt), duration(rtt), color='grey', alpha=0.08)
    ax.grid(alpha=0.2)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=8)


def diagnostics(root, output, protocol, rtt, run, grid, goodput):
    title = f'{PROTOCOLS[protocol][2]} — RTT {rtt} ms — run {run}'
    fig, ax = plt.subplots(figsize=(10, 4))
    for i, name in enumerate(CONNECTIONS):
        ax.plot(grid, goodput[i], color=COLORS[i], label=name, lw=0.9)
    ax.axhline(CAPACITY_MBPS, color='grey', ls='--', lw=0.8, label='Ideal connection max–min')
    decorate(ax, rtt, 'Goodput (Mbps)')
    ax.set_title(title)
    save(fig, output / 'goodput')

    # Match the original parking-lot diagnostics, while preserving subflow IDs.
    for metric, label, scale in (('throughput', 'Subflow delivery (Mbps)', 1e6),
                                  ('cwnd', 'Cwnd (KiB)', 1024),
                                  ('rtt', 'RTT (ms)', 0.001)):
        fig, axes = plt.subplots(2, 2, figsize=(12, 7))
        for i, ax in enumerate(axes.flat):
            if metric == 'throughput':
                # MpTcpConnectionBase only starts this timer on real subflows.
                traces = load(root, f'{SERVERS[i]}.tcp', metric)
            else:
                traces = [(folder.name, read(folder / f'{metric}.csv', metric))
                          for folder in subflows(root, CLIENTS[i])
                          if (folder / f'{metric}.csv').exists()]
            for name, series in traces:
                times, values = series
                ax.plot(times, values / scale,
                        label=name.rsplit('.', 1)[-1], lw=0.8)
            if not traces:
                ax.text(.5, .5, 'No recorded samples', transform=ax.transAxes, ha='center')
            ax.set_title(CONNECTIONS[i])
            decorate(ax, rtt, label)
        fig.suptitle(title)
        save(fig, output / metric)

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for index, (queue, label) in enumerate(QUEUES):
        path = root / f'twoLaneParkingLot.{queue}' / 'queueLength.csv'
        if path.exists():
            times, values = read(path, 'queueLength')
            axes[index // 3].step(times, values, where='post', label=label, lw=0.8)
    for ax in axes:
        decorate(ax, rtt, 'Queue length (packets)')
    fig.suptitle(title)
    save(fig, output / 'queueLength')

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for i, name in enumerate(CONNECTIONS):
        for folder in subflows(root, CLIENTS[i]):
            path = folder / 'subflowSendQueueBytes.csv'
            times, values = read(path, 'subflowSendQueueBytes')
            axes[0].step(times, values / 1024, where='post',
                         label=f'{name}, {folder.name.rsplit(".", 1)[-1]}', lw=0.7)
        traces = load(root, f'{SERVERS[i]}.tcp', 'holBlockedBytes')
        if traces:
            hol = np.sum([sample(s, grid) for _, s in traces], axis=0)
            axes[1].plot(grid, hol / 1024, label=name, color=COLORS[i], lw=0.8)
    decorate(axes[0], rtt, 'Unsent send queue (KiB)')
    decorate(axes[1], rtt, 'Receiver HoL (KiB)')
    fig.suptitle(title)
    save(fig, output / 'transport')


def average_plot(curves, grid, rtt, protocol, output):
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    rows = []
    for i, name in enumerate(CONNECTIONS):
        mean, variance, count = mean_variance(curves[:, i])
        sd = np.sqrt(variance)
        axes[0].plot(grid, mean, label=name, color=COLORS[i])
        axes[0].fill_between(grid, mean - sd, mean + sd, color=COLORS[i], alpha=0.15)
        axes[1].plot(grid, variance, label=name, color=COLORS[i])
        rows.extend(dict(protocol=protocol, rtt_ms=rtt, connection=name, time_s=t,
                         mean_mbps=m, std_mbps=s, variance_mbps2=v, runs=n)
                    for t, m, s, v, n in zip(grid, mean, sd, variance, count))
    decorate(axes[0], rtt, 'Goodput (Mbps), mean ± SD')
    decorate(axes[1], rtt, 'Goodput variance (Mbps²)')
    fig.suptitle(f'{PROTOCOLS[protocol][2]} — RTT {rtt} ms')
    save(fig, output / 'goodput_mean_variance')
    return rows


def comparisons(frame, output):
    metrics = ['goodput_ratio', 'spine_over_max_rib', 'spine_goodput_mbps',
               'rib1_goodput_mbps', 'rib2_goodput_mbps', 'rib3_goodput_mbps']
    summary = frame.groupby(['protocol', 'rtt_ms'])[metrics].agg(['mean', 'std', 'count'])
    summary.columns = ['_'.join(pair) for pair in summary.columns]
    summary = summary.reset_index()
    summary.to_csv(output / 'summary.csv', index=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    for (protocol, (_, _, label)), color in zip(PROTOCOLS.items(), COLORS):
        data = summary[summary.protocol == protocol].sort_values('rtt_ms')
        if not data.empty:
            ax.errorbar(data.rtt_ms, data.goodput_ratio_mean, yerr=data.goodput_ratio_std,
                        marker='o', color=color, label=label, lw=1, capsize=3)
    ax.axhline(1, color='grey', ls='--', lw=.9, label='Ideal connection max–min')
    ax.axhline(1/3, color='black', ls=':', lw=.9, label='Ideal connection proportional fairness')
    ax.set(xlabel='Propagation RTT (ms)', ylabel='Spine / largest rib, min-to-max ratio',
           ylim=(0, 1.08), xticks=RTTS_MS)
    ax.grid(alpha=.2)
    ax.legend(fontsize=8)
    save(fig, output / 'goodput_ratio')

    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    for ax, name, metric in zip(axes.flat, CONNECTIONS, metrics[2:]):
        for (protocol, (_, _, label)), color in zip(PROTOCOLS.items(), COLORS):
            data = summary[summary.protocol == protocol].sort_values('rtt_ms')
            if not data.empty:
                ax.errorbar(data.rtt_ms, data[f'{metric}_mean'], yerr=data[f'{metric}_std'],
                            color=color, marker='o', lw=1, capsize=2, label=label)
        ax.axhline(CAPACITY_MBPS, color='grey', ls='--', lw=.8, label='Ideal max–min')
        pf = CAPACITY_MBPS / 2 if name == 'Spine' else 1.5 * CAPACITY_MBPS
        ax.axhline(pf, color='black', ls=':', lw=.8, label='Ideal proportional fairness')
        ax.set(title=name, xlabel='Propagation RTT (ms)', ylabel='Goodput (Mbps)')
        ax.grid(alpha=.2)
    axes.flat[0].legend(fontsize=7)
    save(fig, output / 'goodput_by_rtt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', type=int, default=list(RUNS))
    parser.add_argument('--configs', nargs='+', default=[p for p, _, _ in configurations()])
    parser.add_argument('--csv-root', type=Path, default=SIM_ROOT / 'experiments/experiment7/csvs')
    parser.add_argument('--out-dir', type=Path, default=SIM_ROOT / 'plots/experiment7')
    args = parser.parse_args()
    if set(args.configs) - {p for p, _, _ in configurations()}:
        parser.error('Unknown configuration prefix')
    if set(args.runs) - set(RUNS):
        parser.error('Runs must be between 1 and 5')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows, coverage, statistics = [], [], []
    for protocol in PROTOCOLS:
        for rtt in RTTS_MS:
            if prefix(protocol, rtt) not in args.configs:
                continue
            case = slug(protocol, rtt)
            grid = np.arange(INTERVAL / 2, duration(rtt), INTERVAL)
            collected = []
            for run in args.runs:
                root = args.csv_root / case / f'run{run}'
                goodput = goodput_curves(root, grid, rtt, run)
                present = all(np.isfinite(s).any() for s in goodput)
                row = dict(protocol=protocol, rtt_ms=rtt, run=run, **fairness_row(goodput, grid, rtt))
                coverage.append(dict(protocol=protocol, rtt_ms=rtt, run=run,
                                     all_connections_present=present,
                                     measurement_coverage=row['coverage_fraction']))
                if not present:
                    print(f'Missing connection goodput: {case}/run{run}')
                    continue
                rows.append(row)
                collected.append(goodput)
                diagnostics(root, args.out_dir / case / f'run{run}', protocol, rtt, run, grid, goodput)
            if collected:
                statistics += average_plot(np.array(collected), grid, rtt, protocol, args.out_dir / case)
    pd.DataFrame(coverage).to_csv(args.out_dir / 'coverage.csv', index=False)
    if not rows:
        print('No complete connection goodput data; no comparison plots produced.')
        return 1
    frame = pd.DataFrame(rows)
    frame.to_csv(args.out_dir / 'run_summary.csv', index=False)
    pd.DataFrame(statistics).to_csv(args.out_dir / 'goodput_time_statistics.csv', index=False)
    comparisons(frame, args.out_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
