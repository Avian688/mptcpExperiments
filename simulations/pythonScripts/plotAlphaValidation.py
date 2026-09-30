#!/usr/bin/env python3
"""MpORB diagnostics, mean/variance curves and allocation-reference comparisons."""
import argparse
from pathlib import Path
import re
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from alphaValidation import SIM_ROOT, DURATIONS, USER_PATHS, cases, phases, reference

COLORS = ('#2878b5', '#e47722', '#31945b')
STEP = 0.5


def read(path, metric):
    frame = pd.read_csv(path)[['time', metric]].replace([np.inf, -np.inf], np.nan).dropna()
    frame = frame.drop_duplicates('time', keep='last').sort_values('time')
    return frame.time.to_numpy(), frame[metric].to_numpy()


def sample(series, grid, rate=False):
    """Interval-end rates; sample-hold states. Missing rate tails stay unknown."""
    t, values = series
    out = np.full(grid.shape, np.nan)
    if not len(t):
        return out
    if rate:
        idx = np.searchsorted(t, grid, side='left')
        valid = idx < len(t)
        # Uncompressed periodic rate vectors: do not fill across missing intervals.
        valid[valid] &= t[idx[valid]] - grid[valid] <= STEP + 1e-8
    else:
        idx = np.searchsorted(t, grid, side='right') - 1
        valid = idx >= 0
    out[valid] = values[idx[valid]]
    return out


def load(root, host, metric):
    return [(p.parent.name, read(p, metric)) for p in sorted(root.glob(f'*/{metric}.csv'))
            if f'.{host}.' in p.parent.name + '.']


def sum_metric(root, host, metric, grid, rate=False):
    traces = load(root, host, metric)
    if not traces:
        return np.full(grid.shape, np.nan)
    return np.sum([sample(s, grid, rate) for _, s in traces], axis=0)


def subflows(root, host):
    # Only real subflows emit this signal; meta cwnd must not enter the plots.
    return sorted((p.parent for p in root.glob('*/subflowSendQueueBytes.csv')
                   if f'.{host}.tcp.' in p.parent.name),
                  key=lambda p: int(re.search(r'conn-(\d+)$', p.name).group(1)))


def decorate(ax, number):
    if number == 1:
        ax.axvspan(60, 120, color='grey', alpha=0.12)
        for t in (60, 120):
            ax.axvline(t, color='grey', ls='--', lw=0.6)
    if number == 6:
        ax.axvspan(60, 65, color='grey', alpha=0.12)
    ax.set_xlim(0, DURATIONS[number])
    ax.set_xlabel('Time (s)')
    ax.grid(alpha=0.2)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7)


def save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path.with_suffix('.png'), dpi=140)
    fig.savefig(path.with_suffix('.pdf'))
    plt.close(fig)


def dashboard(root, number, title, run, grid, goodput, output, protocol='Alpha'):
    fig, axes = plt.subplots(3, 2, figsize=(12, 10))
    axes = axes.ravel()
    for i, name in enumerate('ABC'):
        axes[0].plot(grid, goodput[i], color=COLORS[i], label=name)
        hol = sum_metric(root, f'server[{i}].tcp', 'holBlockedBytes', grid)
        axes[4].plot(grid, hol / 1024, label=name, color=COLORS[i])
    if number == 1:
        extra = np.sum([sum_metric(root, f'server[{i}].app[0]', 'goodput', grid, True)
                        for i in range(3, 7)], axis=0) / 1e6
        axes[0].plot(grid, extra, color='grey', label='Four temporary connections (total)')
    axes[0].set_ylabel('Goodput (Mbps)')
    axes[4].set_ylabel('Receiver HoL (KiB)')
    # Receiver connection IDs are local. Associate path order only within this host.
    for i, name in enumerate('ABC'):
        receiving = load(root, f'server[{i}].tcp', 'throughput')
        receiving.sort(key=lambda p: int(re.search(r'conn-(\d+)$', p[0]).group(1)))
        count = len(USER_PATHS[number][i])
        # The meta connection is created before its subflows; omit it if recorded.
        receiving = receiving[-count:]
        for path, (_, s) in zip(USER_PATHS[number][i], receiving):
            axes[1].plot(grid, sample(s, grid, True) / 1e6, label=f'{name} route {path}', lw=0.7)
    axes[1].set_ylabel('Subflow in-order delivery (Mbps)')
    axes[1].set_title('TCP sequence progress, before connection-level reassembly')
    for ax, metric, scale, label in (
            (axes[2], 'cwnd', 1024, 'Cwnd (KiB)'),
            (axes[3], 'subflowSendQueueBytes', 1024, 'Unsent send queue (KiB)'),
            (axes[5], 'mpOrbBetaWeight' if protocol == 'Beta' else 'semiCoupledAlphaRateShare',
             1, f'{protocol} AI weight')):
        for i, name in enumerate('ABC'):
            for route, folder in zip(USER_PATHS[number][i], subflows(root, f'client[{i}]')):
                p = folder / f'{metric}.csv'
                if p.exists():
                    ax.plot(grid, sample(read(p, metric), grid)/scale, label=f'{name} route {route}', lw=0.7)
        ax.set_ylabel(label)
    for ax in axes:
        decorate(ax, number)
    fig.suptitle(f'MpORB {protocol} — {title} — run {run}')
    save(fig, output / 'response')

    fig, axes = plt.subplots(3, 3, figsize=(15, 11))
    specs = [('U', 1, 'Sender U'), ('sharingFlows', 1, 'Sender N'),
             ('bottleneckBandwidth', 125000, 'Sender B (Mbps)'),
             ('semiCoupledAlphaSubflowRate', 125000, 'Estimated subflow rate (Mbps)'),
             ('semiCoupledAlphaConnectionRate', 125000, 'Estimated connection rate (Mbps)'),
             ('mbytesInFlight', 1024, 'Bytes in flight (KiB)'),
             ('srtt', 0.001, 'Smoothed RTT (ms)'),
             ('cwndLimited', 1, 'Cwnd limited'),
             ('retransmissionRate', 1e6, 'Retransmission rate (Mbps)')]
    for ax, (metric, scale, label) in zip(axes.ravel(), specs):
        for i, name in enumerate('ABC'):
            for route, folder in zip(USER_PATHS[number][i], subflows(root, f'client[{i}]')):
                p = folder / f'{metric}.csv'
                if p.exists():
                    ax.plot(grid, sample(read(p, metric), grid, metric == 'retransmissionRate')/scale,
                            label=f'{name} route {route}', lw=0.7)
        ax.set_ylabel(label)
        decorate(ax, number)
    fig.suptitle(f'{protocol} telemetry — {title} — run {run}')
    save(fig, output / 'telemetry')

    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    for ax, metric, scale, label in zip(axes.ravel(),
            ('queueLength', 'pintLocalUtilization', 'numberOfFlows', 'bandwidth'),
            (1, 1, 1, 1e6), ('Queued packets', 'Switch U', 'Switch N', 'Link capacity (Mbps)')):
        # Select the forward PINT bottlenecks, not every access-link queue.
        for source in sorted(root.glob('*/pintLocalUtilization.csv')):
            p = source.parent / f'{metric}.csv'
            if p.exists():
                label_name = source.parent.name.split('.', 1)[-1]
                ax.plot(grid, sample(read(p, metric), grid)/scale, label=label_name, lw=0.7)
        ax.set_ylabel(label)
        decorate(ax, number)
    fig.suptitle(f'Bottlenecks — {title} — run {run}')
    save(fig, output / 'bottlenecks')


def mean_variance(values):
    count = np.isfinite(values).sum(axis=0)
    mean = np.divide(np.nansum(values, axis=0), count,
                     out=np.full(count.shape, np.nan), where=count > 0)
    variance = np.divide(np.nansum((values - mean)**2, axis=0), count - 1,
                         out=np.full(count.shape, np.nan), where=count > 1)
    return mean, variance, count


def settling(values, target, grid, start, end):
    """Seconds until all ABC 0.5-s bins stay within 5% for five seconds.

    This is relative to the labelled ideal reference, not Alpha's own final rate.
    Never treat failure to settle as a zero-second response.
    """
    mask = (grid >= start) & (grid < end)
    error = np.abs(values[:, mask] - np.array(target)[:, None])
    valid = np.all(error <= 0.05 * np.array(target)[:, None], axis=0)
    samples = int(5/STEP)
    for i in range(len(valid)-samples+1):
        if valid[i:i+samples].all():
            return float(grid[mask][i] - STEP/2 - start)
    return np.nan


def main(number):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', type=int, default=list(range(1, 6)))
    parser.add_argument('--configs', nargs='+', default=[p for p, _, _ in cases(number)])
    parser.add_argument('--csv-root', type=Path, default=SIM_ROOT / 'experiments' / f'experiment{number}' / 'csvs')
    parser.add_argument('--out-dir', type=Path, default=SIM_ROOT / 'plots' / f'experiment{number}')
    args = parser.parse_args()
    if set(args.configs) - {p for p, _, _ in cases(number)}:
        parser.error('Unknown configuration prefix')
    grid = np.arange(STEP/2, DURATIONS[number], STEP)
    rows, stats, coverage, curves = [], [], [], {}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for prefix, slug, title in cases(number):
        if prefix not in args.configs:
            continue
        protocol = prefix.split('_', 1)[0]
        collected = []
        for run in args.runs:
            root = args.csv_root / slug / f'run{run}'
            goodput = np.array([sum_metric(root, f'server[{i}].app[0]', 'goodput', grid, True)/1e6
                                for i in range(3)])
            complete = all(np.isfinite(s).any() for s in goodput)
            coverage.append(dict(case=slug, protocol=protocol, run=run, goodput_present=complete))
            if not complete:
                print(f'Missing A/B/C goodput: {slug}/run{run}')
                continue
            collected.append(goodput)
            dashboard(root, number, title, run, grid, goodput, args.out_dir / slug / f'run{run}', protocol)
            for start, end, phase in phases(number):
                target = reference(number, phase)
                row = dict(case=slug, protocol=protocol, run=run, phase=phase, start_s=start, end_s=end,
                           ideal_maxmin_settling_s=settling(goodput, target, grid, start, end))
                for i, name in enumerate('ABC'):
                    mask = (grid >= start) & (grid < end)
                    tail = (grid >= end-20) & (grid < end)
                    valid = np.isfinite(goodput[i, mask])
                    row[f'{name}_coverage_fraction'] = float(valid.mean())
                    # Do not quietly turn missing intervals into zero delivered bytes.
                    row[f'{name}_delivered_MB'] = float(np.sum(goodput[i, mask])*STEP/8) if valid.all() else np.nan
                    row[f'{name}_final20s_mbps'] = float(np.mean(goodput[i, tail]))
                    row[f'{name}_ideal_maxmin_mbps'] = target[i]
                    row[f'{name}_ideal_pf_mbps'] = reference(number, phase, 'pf')[i]
                rows.append(row)
        if not collected:
            continue
        curves[slug] = np.array(collected)
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        for i, name in enumerate('ABC'):
            mean, variance, count = mean_variance(curves[slug][:, i])
            sd = np.sqrt(variance)
            axes[0].plot(grid, mean, color=COLORS[i], label=name)
            axes[0].fill_between(grid, mean-sd, mean+sd, color=COLORS[i], alpha=0.15)
            axes[1].plot(grid, variance, color=COLORS[i], label=name)
            stats.extend(dict(case=slug, protocol=protocol, connection=name, time_s=t, mean_mbps=m,
                              variance_mbps2=v, available_runs=int(n))
                         for t, m, v, n in zip(grid, mean, variance, count))
        axes[0].set_ylabel('Mean goodput ± 1 SD (Mbps)')
        axes[1].set_ylabel('Sample variance (Mbps²)')
        for ax in axes:
            decorate(ax, number)
            ax.set_ylim(bottom=0)
        fig.suptitle(f'MpORB {protocol} — {title}')
        save(fig, args.out_dir / slug / 'goodput_mean_variance')
    pd.DataFrame(coverage).to_csv(args.out_dir / 'coverage.csv', index=False)
    if not rows:
        print('No A/B/C goodput available. Run export and extraction first.')
        return 1
    frame = pd.DataFrame(rows)
    frame.to_csv(args.out_dir / 'phase_runs.csv', index=False)
    numeric = frame.select_dtypes(include='number').columns.drop('run')
    frame.groupby(['case', 'phase'], sort=False)[numeric].agg(['mean', 'std', 'count']).to_csv(args.out_dir / 'phase_summary.csv')
    pd.DataFrame(stats).to_csv(args.out_dir / 'goodput_time_statistics.csv', index=False)
    # Point/line comparisons with SD, never bar charts. RTT is the sweep axis.
    fig, axes = plt.subplots(1, len(phases(number)), figsize=(max(9, 5*len(phases(number))), 4.5), squeeze=False)
    for ax, (_, _, phase) in zip(axes.ravel(), phases(number)):
        part = frame[frame.phase == phase]
        slugs = [slug for _, slug, _ in cases(number) if slug in part.case.values]
        if number == 5:
            for protocol, group in part.groupby('protocol', sort=False):
                mean = [group[f'{name}_final20s_mbps'].mean() for name in 'ABC']
                sd = [group[f'{name}_final20s_mbps'].std() for name in 'ABC']
                ax.errorbar(range(3), mean, yerr=sd, marker='o', capsize=3, label=protocol)
            ax.plot(range(3), reference(number, phase), ':', color='black', label='Ideal max–min')
            ax.plot(range(3), reference(number, phase, 'pf'), '--', color='#31945b', label='Ideal PF')
            ax.set_xticks(range(3), list('ABC'))
            ax.set_xlabel('Connection')
            ax.set_ylabel('Final 20 s goodput (Mbps)')
            ax.set_ylim(bottom=0)
            ax.grid(alpha=0.2)
            ax.legend()
            continue
        if number == 6:
            orders = ['Together', 'AFirst', 'BCFirst']
            for protocol, group in part.groupby('protocol', sort=False):
                group = group.assign(order=group.case.str.removeprefix('beta_'))
                for i, name in enumerate('ABC'):
                    grouped = group.groupby('order')[f'{name}_final20s_mbps'].agg(['mean', 'std']).reindex(orders)
                    ax.errorbar(range(3), grouped['mean'], yerr=grouped['std'],
                                marker='o' if protocol == 'Alpha' else 's', capsize=3,
                                ls='-' if protocol == 'Alpha' else '--', color=COLORS[i],
                                label=f'{protocol}: {name}')
            ax.axhline(reference(number, phase)[0], color='black', ls=':', label='Ideal max–min')
            ax.set_xticks(range(3), ['Together', 'A first', 'B/C first'])
            ax.set_xlabel('Arrival order')
            ax.set_ylabel('Final 20 s goodput (Mbps)')
            ax.set_title(phase)
            ax.grid(alpha=0.2)
            ax.legend()
            continue
        x = [int(s.split('_')[-1]) for s in slugs] if number == 1 else list(range(len(slugs)))
        for i, name in enumerate('ABC'):
            grouped = part.groupby('case')[f'{name}_final20s_mbps'].agg(['mean', 'std']).reindex(slugs)
            ax.errorbar(x, grouped['mean'], yerr=grouped['std'], marker='o', capsize=3, color=COLORS[i], label=name)
            target = reference(number, phase)[i]
            ax.axhline(target, color=COLORS[i], ls=':', lw=0.8)
            if number == 5:
                ax.axhline(reference(number, phase, 'pf')[i], color=COLORS[i], ls='--', lw=0.8)
        if number != 1:
            ax.set_xticks(x, slugs)
        ax.set_xlabel('Path 2 RTT (ms); path 1 = 20 ms' if number == 1 else 'Case')
        ax.set_ylabel('Final 20 s goodput (Mbps)')
        ax.set_title(phase)
        ax.grid(alpha=0.2)
        ax.legend()
    fig.suptitle('Mean ± sample SD; dotted = ideal max–min' + ('; dashed = ideal PF' if number == 5 else ''))
    save(fig, args.out_dir / 'allocation_comparison')
    print(f'Wrote plots and CSV summaries to {args.out_dir}')
    return 0


if __name__ == '__main__':
    experiment = int(sys.argv.pop(1))
    raise SystemExit(main(experiment))
