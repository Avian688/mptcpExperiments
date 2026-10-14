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

from experimentProtocols import CC_LABELS, CC_COLORS

COLORS = ('#2878b5', '#e47722', '#31945b')
STEP = 0.5
STYLES = {'Alpha': ('o', '-'), 'OrbUncoupled': ('s', '--'),
          'CubicUncoupled': ('^', '-.'), 'Delta': ('D', ':'), 'Omega': ('P', '-')}


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
            (axes[5], 'semiCoupledAlphaRateShare' if protocol in ('Alpha', 'Delta', 'Omega') else 'mbytesInFlight',
             1 if protocol in ('Alpha', 'Delta', 'Omega') else 1024,
             'Alpha AI weight' if protocol in ('Alpha', 'Delta', 'Omega') else 'Bytes in flight (KiB)')):
        for i, name in enumerate('ABC'):
            for route, folder in zip(USER_PATHS[number][i], subflows(root, f'client[{i}]')):
                p = folder / f'{metric}.csv'
                if p.exists():
                    ax.plot(grid, sample(read(p, metric), grid)/scale, label=f'{name} route {route}', lw=0.7)
        ax.set_ylabel(label)
    for ax in axes:
        decorate(ax, number)
    fig.suptitle(f'{protocol} — {title} — run {run}')
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



def arrival_allocation_comparisons(frame, output):
    """Separate arrival cases; show each run and mean ± SD on common axes."""
    output.mkdir(parents=True, exist_ok=True)
    for suffix in ('png', 'pdf'):
        (output / f'allocation_comparison.{suffix}').unlink(missing_ok=True)
    protocols = [p for p in CC_LABELS if p in set(frame.protocol)]
    frame = frame.copy()
    frame['order'] = [case.removeprefix(f'{protocol.lower()}_')
                      for case, protocol in zip(frame.case, frame.protocol)]
    target = reference(6, 'All connections active')
    # Include error bars, all runs and targets; keep the same y scale in all figures.
    upper = max(target)
    for name in 'ABC':
        metric = f'{name}_final20s_mbps'
        stats = frame.groupby(['order', 'protocol'])[metric].agg(['mean', 'std', 'max'])
        candidates = pd.concat([stats['max'], stats['mean'] + stats['std'].fillna(0)]).dropna()
        if not candidates.empty:
            upper = max(upper, candidates.max())
    for order, title in [('Together', 'Together'), ('AFirst', 'A first'), ('BCFirst', 'B/C first')]:
        part = frame[frame.order == order]
        if part.empty:
            continue
        fig, axes = plt.subplots(1, 3, figsize=(16, 5.5), sharey=True)
        for i, (ax, name) in enumerate(zip(axes, 'ABC')):
            for j, protocol in enumerate(protocols):
                values = part.loc[part.protocol == protocol, f'{name}_final20s_mbps'].dropna().to_numpy()
                if not len(values):
                    continue
                color = CC_COLORS[protocol]
                jitter = np.linspace(-.10, .10, len(values)) if len(values) > 1 else [0]
                ax.scatter(j + np.asarray(jitter), values, color=color, alpha=.35, s=25)
                sd = values.std(ddof=1) if len(values) > 1 else 0
                ax.errorbar(j, values.mean(), yerr=sd, fmt='o', color=color, ms=8, capsize=5)
            ax.axhline(target[i], color='#555555', ls='--', lw=1.2)
            ax.set(xticks=range(len(protocols)),
                   xticklabels=[CC_LABELS[p].replace(' uncoupled', '\nuncoupled') for p in protocols],
                   xlim=(-.5, len(protocols)-.5), ylim=(0, upper * 1.12), title=f'Connection {name}')
            ax.tick_params(axis='x', labelsize=10, pad=8)
            ax.grid(axis='y', alpha=.2)
            ax.spines[['top', 'right']].set_visible(False)
        axes[0].set_ylabel('Final 20 s goodput (Mbps)')
        fig.suptitle(f'ABC allocation — {title}', fontsize=16)
        fig.text(.5, .89, 'Faint dots: individual runs • Solid dots and whiskers: mean ± sample SD • Dashed line: ideal max–min',
                 ha='center', fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, .85))
        for suffix in ('png', 'pdf'):
            fig.savefig(output / f'allocation_comparison_{order}.{suffix}', dpi=180, bbox_inches='tight')
        plt.close(fig)


def allocation_comparison(frame, number, output):
    """One connection per panel, algorithm colours shared across all panels."""
    if number == 6:
        return arrival_allocation_comparisons(frame, output)
    labels = CC_LABELS
    palette = CC_COLORS
    protocols = [p for p in labels if p in set(frame.protocol)]
    phase_names = [name for _, _, name in phases(number)]
    fig, axes = plt.subplots(len(phase_names), 3,
                             figsize=(15, 4 * len(phase_names) + 1.2),
                             squeeze=False, sharey=True)
    for row, phase in enumerate(phase_names):
        part = frame[frame.phase == phase]
        for col, name in enumerate('ABC'):
            ax = axes[row, col]
            metric = f'{name}_final20s_mbps'
            for j, protocol in enumerate(protocols):
                group = part[part.protocol == protocol].copy()
                color = palette[protocol]
                if number == 5:
                    values = group[metric].dropna().to_numpy()
                    if not len(values):
                        continue
                    ax.scatter(j + np.linspace(-.08, .08, len(values)), values,
                               s=22, color=color, alpha=.35, zorder=2)
                    ax.errorbar(j, values.mean(),
                                yerr=values.std(ddof=1) if len(values) > 1 else None,
                                fmt='o', color=color, capsize=4, ms=7,
                                label=labels[protocol], zorder=3)
                else:
                    group['rtt'] = group.case.str.rsplit('_', n=1).str[-1].astype(int)
                    stats = group.groupby('rtt')[metric].agg(['mean', 'std']).sort_index()
                    ax.plot(stats.index, stats['mean'], marker=STYLES[protocol][0],
                            color=color, lw=1.7, ms=4, label=labels[protocol])
                    ax.fill_between(stats.index, stats['mean']-stats['std'],
                                    stats['mean']+stats['std'], color=color, alpha=.10)
            ax.axhline(reference(number, phase)[col], color='#444444', ls='--',
                       lw=1.2, label='Ideal max–min', zorder=1)
            if number == 5:
                ax.axhline(reference(number, phase, 'pf')[col], color='#888888',
                           ls=':', lw=1.5, label='Ideal proportional fairness', zorder=1)
                ax.set_xticks(range(len(protocols)), [labels[p].replace(' ', '\n', 1) for p in protocols])
                ax.set_xlim(-.5, len(protocols)-.5)
            else:
                ax.set_xticks([20, 60, 100, 140, 180, 200])
                ax.set_xlabel('Path 2 RTT (ms); path 1 = 20 ms')
            ax.set_title(f'Connection {name}' + (f' · {phase}' if len(phase_names)>1 else ''), fontsize=12)
            ax.set_ylim(bottom=0)
            ax.grid(axis='y', alpha=.2)
            ax.spines[['top', 'right']].set_visible(False)
            if col == 0:
                ax.set_ylabel('Final 20 s goodput (Mbps)')
    # Shared axes must include every connection's reference, including B/C's
    # larger PF target; setting a limit in the first panel stops later autoscaling.
    tops = [float(frame[f'{name}_final20s_mbps'].max()) for name in 'ABC']
    for phase in phase_names:
        tops.extend(reference(number, phase))
        if number == 5:
            tops.extend(reference(number, phase, 'pf'))
    for ax in axes.flat:
        for collection in ax.collections:
            bounds = collection.get_datalim(ax.transData)
            if np.isfinite(bounds.ymax):
                tops.append(bounds.ymax)
    axes[0, 0].set_ylim(0, max([v for v in tops if np.isfinite(v)] + [1]) * 1.08)
    handles, texts = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, texts, loc='upper center', bbox_to_anchor=(.5, .945),
               ncol=3, frameon=False, fontsize=10)
    fig.suptitle('Connection allocation — mean ± sample SD across runs', fontsize=15, y=.995)
    fig.tight_layout(rect=(0, 0, 1, .84 if len(phase_names)==1 else .92))
    output.mkdir(parents=True, exist_ok=True)
    for suffix in ('png', 'pdf'):
        fig.savefig(output / f'allocation_comparison.{suffix}', dpi=180, bbox_inches='tight')
    plt.close(fig)


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
        fig.suptitle(f'{protocol} — {title}')
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
    allocation_comparison(frame, number, args.out_dir)
    print(f'Wrote plots and CSV summaries to {args.out_dir}')
    return 0


if __name__ == '__main__':
    experiment = int(sys.argv.pop(1))
    raise SystemExit(main(experiment))
