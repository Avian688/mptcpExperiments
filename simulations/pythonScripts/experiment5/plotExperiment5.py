#!/usr/bin/env python3
"""Phase-aware plots for experiment 5; background traffic is always MPORB."""
from pathlib import Path
import argparse
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'experiment2'))
from plotExperiment2 import (PROTOCOLS, USERS, USER_PATH_IDS, load_bundle, read_series, resample)
from generateExperiment5IniFiles import WAVES

PHASES = ((0, 30, 'Initial'), (30, 60, 'Load P5/P6'), (60, 90, 'Recovery 1'),
          (90, 120, 'Load P1/P2'), (120, 150, 'Recovery 2'))
GRID = np.arange(0.25, 150, 0.5)


def rates(series):
    # Goodput/throughput signals describe the preceding 0.5-second interval.
    # Shift their timestamps before holding compressed repeated samples.
    shifted = series.copy()
    shifted.index = shifted.index - 0.5
    return resample(shifted, GRID).to_numpy() / 1e6


def backgrounds(root):
    result = {}
    for path, first, start, stop in WAVES:
        traces = []
        for i in range(first, first + 5):
            s = read_series(root / f'sharedleopaths.backgroundServer[{i}].app[0]' / 'goodput.csv', 'goodput')
            if s is None or s.empty:
                print(f'Warning: missing background {i} goodput in {root}')
                traces = []
                break
            traces.append(rates(s))
        # Missing measurements remain unknown, rather than becoming zero load.
        result[path] = np.sum(traces, axis=0) if traces else np.full(len(GRID), np.nan)
    return result


def mark(ax):
    ax.axvspan(30, 60, color='#edb04b', alpha=0.16)
    ax.axvspan(90, 120, color='#9b80d0', alpha=0.14)
    for t in (30, 60, 90, 120):
        ax.axvline(t, color='gray', lw=0.7, ls='--')
    ax.set_xlim(0, 150)
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8, ncol=4, loc='upper right')


def dashboard(bundle, bg, out):
    fig, axes = plt.subplots(6, 1, figsize=(12, 16), sharex=True)
    for user, _, _ in USERS:
        axes[0].plot(GRID, rates(bundle.user_goodput[user]), label=user)
    axes[0].set_ylabel('Goodput (Mbps)')
    axes[0].set_title('Main connections A, B, C')
    for path, values in bg.items():
        axes[1].plot(GRID, values, label=f'Path {path}: five flows')
    axes[1].set_ylabel('Goodput (Mbps)')
    axes[1].set_title('Background MPORB connections (sum per path)')
    for ax, (user, _, _) in zip(axes[2:5], USERS):
        for path, series in zip(USER_PATH_IDS[user], bundle.subflow_throughput[user]):
            ax.plot(GRID, rates(series), label=f'Path {path}')
        ax.set_ylabel('Throughput (Mbps)')
        ax.set_title(f'{user}: received subflow throughput (includes retransmissions)')
    for path, series in bundle.queues.items():
        axes[5].plot(GRID, resample(series, GRID), label=f'Path {path}')
    axes[5].set_ylabel('Queued packets')
    for ax in axes:
        mark(ax)
    axes[-1].set_xlabel('Time (s); shaded regions show scheduled background load')
    fig.suptitle(f'{bundle.label} — run {bundle.run}', fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out/'response.png', dpi=150)
    fig.savefig(out/'response.pdf')
    plt.close(fig)


def phase_rows(bundle, bg):
    rows = []
    traces = {f'{user}_goodput_mbps': rates(bundle.user_goodput[user]) for user, _, _ in USERS}
    traces.update({f'background_path_{p}_goodput_mbps': s for p, s in bg.items()})
    for user, _, _ in USERS:
        for p, s in zip(USER_PATH_IDS[user], bundle.subflow_throughput[user]):
            traces[f'{user}_path_{p}_throughput_mbps'] = rates(s)
    for p, s in bundle.queues.items():
        traces[f'path_{p}_queue_packets'] = resample(s, GRID).to_numpy()
    for start, end, phase in PHASES:
        for window, low in (('whole_phase', start), ('last_10s', end - 10)):
            mask = (GRID >= low) & (GRID < end)
            row = dict(protocol=bundle.protocol, label=bundle.label, run=bundle.run,
                       phase=phase, window=window, start_s=low, end_s=end)
            row.update({name: float(np.mean(values[mask])) for name, values in traces.items()})
            rows.append(row)
    return rows


def heatmaps(frame, out):
    data = frame[frame.window == 'last_10s']
    labels = list(dict.fromkeys(data.label))
    fig, axes = plt.subplots(1, 3, figsize=(max(15, len(labels)*3), 6), sharey=True)
    for ax, user in zip(axes, ('A', 'B', 'C')):
        stat = data.groupby(['phase', 'label'])[f'{user}_goodput_mbps'].agg(['mean', 'std', 'count'])
        matrix = np.full((5, len(labels)), np.nan)
        for i, (_, _, phase) in enumerate(PHASES):
            for j, label in enumerate(labels):
                if (phase, label) in stat.index:
                    matrix[i, j] = stat.loc[(phase, label), 'mean']
        im = ax.imshow(np.ma.masked_invalid(matrix), cmap='viridis', vmin=0, vmax=120, aspect='auto')
        for i, (_, _, phase) in enumerate(PHASES):
            for j, label in enumerate(labels):
                if np.isfinite(matrix[i, j]):
                    s = stat.loc[(phase, label)]
                    sd = f'{s["std"]:.1f}' if s['count'] > 1 else '—'
                    ax.text(j, i, f'{s["mean"]:.1f}\n±{sd}\nn={int(s["count"])}',
                            ha='center', va='center', fontsize=7, color='white' if s['mean'] < 65 else 'black')
        ax.set_xticks(range(len(labels)), labels, rotation=60, ha='right')
        ax.set_yticks(range(5), [p[2] for p in PHASES])
        ax.set_title(f'Connection {user}')
    fig.suptitle('Final 10 seconds of each phase: mean ± sample SD across runs')
    fig.subplots_adjust(bottom=0.28, top=0.88, right=0.90, wspace=0.15)
    fig.colorbar(im, cax=fig.add_axes((0.92, 0.28, 0.012, 0.60)), label='Goodput (Mbps)')
    fig.savefig(out/'phase_goodput.png', dpi=180)
    fig.savefig(out/'phase_goodput.pdf')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument('--protocols', nargs='+', default=[p for p, _ in PROTOCOLS])
    parser.add_argument('--csv-root', type=Path, default=HERE.parents[1]/'experiments/experiment5/csvs')
    parser.add_argument('--out-dir', type=Path, default=HERE.parents[1]/'plots/experiment5')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for protocol, label in PROTOCOLS + [('cubic', 'CUBIC Uncoupled')]:
        if protocol not in args.protocols:
            continue
        for run in args.runs:
            if not (args.csv_root/protocol/f'run{run}').exists():
                continue
            bundle = load_bundle(args.csv_root, protocol, label, run)
            if bundle is None:
                continue
            bg = backgrounds(args.csv_root/protocol/f'run{run}')
            dashboard(bundle, bg, args.out_dir/'individual'/protocol/f'run{run}')
            rows.extend(phase_rows(bundle, bg))
    if not rows:
        print('No complete A/B/C bundles to plot.')
        return 1
    frame = pd.DataFrame(rows)
    frame.to_csv(args.out_dir/'phase_runs.csv', index=False)
    metrics = [c for c in frame if c.endswith(('_mbps', '_packets'))]
    frame.groupby(['protocol', 'phase', 'window'])[metrics].agg(['mean', 'std', 'count']).to_csv(args.out_dir/'phase_summary.csv')
    heatmaps(frame, args.out_dir)
    print(f'Wrote phase summaries and response plots to {args.out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
