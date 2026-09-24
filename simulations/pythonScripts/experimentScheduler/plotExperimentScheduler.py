#!/usr/bin/env python3
"""Compare scheduler goodput and expose sender backlog versus receiver blocking."""
from pathlib import Path
import argparse
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from generateExperimentSchedulerIniFiles import PROFILES, SCHEDULERS, config_prefix

SIM_ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = SIM_ROOT / 'experiments/experimentScheduler/csvs'
OUT = SIM_ROOT / 'plots/experimentScheduler/alpha'
PHASES = {'baseline': (10, 40), 'competition': (40, 80), 'recovery': (80, 120)}
COLORS = {'default': '#2878b5', 'defaultCwnd': '#31945b', 'intInformed': '#e47722'}


def read_series(path, metric):
    frame = pd.read_csv(path)[['time', metric]].dropna()
    frame = frame.drop_duplicates('time', keep='last').sort_values('time')
    return frame.time.to_numpy(), frame[metric].to_numpy()


def sample(series, grid, interval_end=False):
    t, v = series
    if not len(t):
        return np.full_like(grid, np.nan)
    # Goodput is an interval average reported at its end; state vectors hold forward.
    idx = np.searchsorted(t, grid, side='left' if interval_end else 'right')
    if not interval_end:
        idx -= 1
    out = np.zeros_like(grid, dtype=float)
    valid = (idx >= 0) & (idx < len(t))
    out[valid] = v[idx[valid]]
    if not interval_end:
        out[idx >= len(t)] = v[-1]
    return out


def aggregate(series, grid, metric, maximum=False):
    if not series:
        return np.full_like(grid, np.nan)
    values = np.array([sample(s, grid, metric == 'goodput') for s in series])
    return np.max(values, axis=0) if maximum else np.sum(values, axis=0)


def phase_mean(series, metric, start, end, maximum=False):
    if not series:
        return np.nan
    # Exact integration of recorded piecewise-constant samples, not an event average.
    times = np.unique(np.concatenate(([start, end], *[s[0] for s in series])))
    times = times[(times >= start) & (times <= end)]
    mid = (times[:-1] + times[1:]) / 2
    values = aggregate(series, mid, metric, maximum)
    return np.sum(values * np.diff(times)) / (end - start)


def load(root, metric, host):
    return [read_series(p, metric) for p in sorted(root.glob(f'*/{metric}.csv'))
            if f'.{host}' in p.parent.name]


def decorate(ax):
    ax.axvspan(40, 80, color='grey', alpha=0.12)
    ax.set_xlim(0, 120)
    ax.grid(alpha=0.2)


def save(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path.with_suffix('.png'), dpi=160)
    fig.savefig(path.with_suffix('.pdf'))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', nargs='+', type=int, default=list(range(1, 6)))
    parser.add_argument('--configs', nargs='+', default=[config_prefix(p, s) for p in PROFILES for s in SCHEDULERS])
    args = parser.parse_args()
    grid = np.arange(0.25, 120, 0.5)
    curves, rows, coverage = {}, [], []
    missing = []
    for profile in PROFILES:
        for scheduler in SCHEDULERS:
            if config_prefix(profile, scheduler) not in args.configs:
                continue
            group = []
            for run in args.runs:
                root = CSV_ROOT / f'alpha_{profile}_{scheduler}' / f'run{run}'
                main_gp = load(root, 'goodput', 'server[0].app')
                if not main_gp:
                    missing.append(f'{profile}/{scheduler}/run{run}')
                    continue
                bg_gp = load(root, 'goodput', 'backgroundServer[')
                hol = load(root, 'holBlockedBytes', 'server[0].tcp.')
                queues = load(root, 'subflowSendQueueBytes', 'client[0].tcp.')
                group.append(aggregate(main_gp, grid, 'goodput') / 1e6)
                fig, axes = plt.subplots(3, 2, figsize=(12, 10))
                axes = axes.ravel()
                axes[0].plot(grid, group[-1], label='Goodput')
                axes[0].plot(grid, aggregate(bg_gp, grid, 'goodput') / 1e6, label='Background total')
                axes[0].set_ylabel('Goodput (Mbps)')
                # Identify real subflows by the queue signal; do not include meta cwnd.
                subflows = sorted((p.parent for p in root.glob('*/subflowSendQueueBytes.csv')
                                   if '.client[0].tcp.' in p.parent.name),
                                  key=lambda p: int(re.search(r'conn-(\d+)$', p.name).group(1)))
                for ax, metric, scale, label in [
                        (axes[1], 'cwnd', 1024, 'Cwnd (KiB)'),
                        (axes[2], 'subflowSendQueueBytes', 1024, 'Unsent send queue (KiB)'),
                        (axes[3], 'mbytesInFlight', 1024, 'Bytes in flight (KiB)'),
                        (axes[5], 'mpOrbForwardQueueingDelay', 0.001, 'Forward queueing delay (ms)')]:
                    for i, folder in enumerate(subflows):
                        path = folder / f'{metric}.csv'
                        if path.exists():
                            t, v = read_series(path, metric)
                            ax.step(t, v / scale, where='post', label=f'Subflow {i+1} ({folder.name.split(".")[-1]})', linewidth=0.8)
                    ax.set_ylabel(label)
                axes[4].plot(grid, aggregate(hol, grid, 'holBlockedBytes', True) / 1024)
                axes[4].set_ylabel('Receiver HoL bytes (KiB)')
                for ax in axes:
                    decorate(ax)
                    ax.set_xlabel('Time (s)')
                    if ax.get_legend_handles_labels()[0]:
                        ax.legend(fontsize=7)
                fig.suptitle(f'MpORB Alpha — {scheduler}, RTT {PROFILES[profile]} ms, run {run}')
                save(fig, OUT / profile / scheduler / f'run{run}')
                for phase, (start, end) in PHASES.items():
                    rows.append(dict(profile=profile, scheduler=scheduler, run=run, phase=phase,
                        start_s=start, end_s=end,
                        foreground_goodput_mbps=phase_mean(main_gp, 'goodput', start, end)/1e6,
                        background_goodput_mbps=phase_mean(bg_gp, 'goodput', start, end)/1e6,
                        receiver_hol_bytes=phase_mean(hol, 'holBlockedBytes', start, end, True),
                        sender_unsent_bytes=phase_mean(queues, 'subflowSendQueueBytes', start, end)))
            if group:
                curves[profile, scheduler] = np.array(group)
            coverage.append(dict(profile=profile, scheduler=scheduler, available_runs=len(group), requested_runs=len(args.runs)))
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coverage).to_csv(OUT/'coverage.csv', index=False)
    if not rows:
        raise SystemExit('No extracted goodput found; run stages 1–3 first.')
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT/'phase_summary.csv', index=False)
    summary.groupby(['profile','scheduler','phase'], sort=False)[[
        'foreground_goodput_mbps','background_goodput_mbps','receiver_hol_bytes','sender_unsent_bytes'
    ]].agg(['mean','std','count']).to_csv(OUT/'phase_aggregate.csv')
    fig, axes = plt.subplots(len(PROFILES), 1, figsize=(10, 7), squeeze=False)
    for ax, profile in zip(axes.ravel(), PROFILES):
        for scheduler in SCHEDULERS:
            values = curves.get((profile, scheduler))
            if values is None:
                continue
            ax.plot(grid, values.mean(axis=0), label=scheduler, color=COLORS[scheduler])
            ax.fill_between(grid, values.min(axis=0), values.max(axis=0), alpha=0.15, color=COLORS[scheduler])
        ax.set_title(f'RTT {PROFILES[profile][0]}/{PROFILES[profile][1]} ms')
        ax.set_ylabel('Goodput (Mbps)')
        decorate(ax)
        ax.legend()
    axes[-1,0].set_xlabel('Time (s); line = run mean, shading = run range')
    save(fig, OUT/'goodput_comparison')
    # Mean and sample variance across runs, at each time bin. Variance has
    # squared units; show it separately rather than adding it to the mean.
    fig, axes = plt.subplots(2, len(PROFILES), figsize=(12, 7), squeeze=False)
    stats = []
    for j, profile in enumerate(PROFILES):
        for scheduler in SCHEDULERS:
            values = curves.get((profile, scheduler))
            if values is None:
                continue
            mean = values.mean(axis=0)
            variance = values.var(axis=0, ddof=1) if len(values)>1 else np.full_like(mean, np.nan)
            std = np.sqrt(variance)
            axes[0,j].plot(grid, mean, label=scheduler, color=COLORS[scheduler])
            if len(values)>1:
                axes[0,j].fill_between(grid, mean-std, mean+std, color=COLORS[scheduler], alpha=0.15)
                axes[1,j].plot(grid, variance, label=scheduler, color=COLORS[scheduler])
            for t, m, v in zip(grid, mean, variance):
                stats.append(dict(profile=profile, scheduler=scheduler, time_s=t,
                                  mean_mbps=m, variance_mbps2=v, runs=len(values)))
        axes[0,j].set_title(f'RTT {PROFILES[profile][0]}/{PROFILES[profile][1]} ms')
        axes[0,j].set_ylabel('Mean goodput ± 1 SD (Mbps)')
        axes[1,j].set_ylabel('Goodput variance (Mbps²)')
        axes[1,j].set_xlabel('Time (s)')
        for ax in axes[:,j]:
            decorate(ax)
            ax.set_ylim(bottom=0)
            if ax.get_legend_handles_labels()[0]:
                ax.legend()
    save(fig, OUT/'goodput_mean_variance')
    pd.DataFrame(stats).to_csv(OUT/'goodput_time_statistics.csv', index=False)

    # Per-run points expose the distribution; larger markers show mean ± SD.
    fig, axes = plt.subplots(len(PROFILES), len(PHASES), figsize=(12, 6), squeeze=False)
    for i, profile in enumerate(PROFILES):
        for j, phase in enumerate(PHASES):
            ax=axes[i,j]
            for k, scheduler in enumerate(SCHEDULERS):
                vals=summary.loc[(summary.profile==profile)&(summary.scheduler==scheduler)&(summary.phase==phase), 'foreground_goodput_mbps']
                if len(vals):
                    offsets = np.linspace(-0.13, 0.13, len(vals)) if len(vals)>1 else np.array([0.])
                    ax.scatter(k+offsets, vals, color=COLORS[scheduler], alpha=0.45, s=22)
                    ax.errorbar(k, vals.mean(), yerr=vals.std(ddof=1) if len(vals)>1 else None,
                                fmt='D', color=COLORS[scheduler], capsize=5, markersize=6)
            ax.set_xticks(range(len(SCHEDULERS)), SCHEDULERS, rotation=15)
            ax.set_xlim(-0.5, len(SCHEDULERS)-0.5)
            ax.set_ylim(bottom=0)
            ax.grid(axis='y', alpha=0.2)
            ax.set_title(f'{profile}: {phase}')
            ax.set_ylabel('Phase goodput (Mbps)')
    fig.suptitle('Individual runs and mean ± 1 sample standard deviation')
    save(fig, OUT/'phase_goodput')
    print(f'Wrote plots and summaries to {OUT}')
    if missing:
        raise SystemExit('Incomplete requested data: '+', '.join(missing))


if __name__ == '__main__':
    main()
