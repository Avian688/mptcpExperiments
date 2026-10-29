"""Per-terminal application goodput, fairness, and requested-rank availability."""
import json
import math
import re
import tempfile
from pathlib import Path

import numpy as np
from leoExperiments import experiment_directory, SIMULATIONS_DIR, PROTOCOL_ORDER, PAIRS
from experimentProtocols import CC_LABELS, CC_COLORS
from extractionResources import extraction_workers
from parallelProcessing import run_parallel
from extractSingleCsvFile import (read_csv_file, rate_series, sample_hold, write_csv,
                                  ARRAY_BLOCK, discard_pages)


def jain(values):
    values = np.asarray(values, dtype=float)
    if not len(values) or np.any(~np.isfinite(values)) or np.sum(values ** 2) == 0:
        return math.nan
    return float(np.sum(values) ** 2 / (len(values) * np.sum(values ** 2)))


def extract_config(config):
    directory = experiment_directory(config['experiment']) / 'csvs'
    raw = directory / 'raw' / f'{config["config"]}.csv'
    out = directory / 'extracted' / config['config']
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='leo-vectors-') as scratch:
        vectors, scalars = read_csv_file(raw, scratch)
        start, end = config['measurement_start'], config['measurement_end']
        grid = np.arange(0, config['sim_time'], 1.)
        path_grid = np.arange(start + .000002, end, .1)
        connections, paths = [], []
        series = {'time': grid}
        availability = []
        for connection in config['connections']:
            index = connection['index']
            source = f'.userTerminal[{connection["source"]}]'
            destination = f'.userTerminal[{connection["destination"]}].app[0]'
            byte_scalars = [v for (module, metric), v in scalars.items()
                            if module.endswith(destination) and metric == 'bytesRcvd']
            if len(byte_scalars) != 1 or not math.isfinite(byte_scalars[0]) or byte_scalars[0] < 0:
                raise ValueError(f'{config["config"]}: invalid or missing receiver scalar for connection {index}')
            delivered = byte_scalars[0]
            rates = [v for (module, metric), v in vectors.items()
                     if destination + '.thread_' in module and metric == 'goodput']
            mean, trace = rate_series(rates, grid, start, end, delivered)
            late = any(len(t) and t[0] > start for t, _ in rates)
            if late:
                mean = math.nan
            rtt_sum, rtt_count = 0., 0
            for (module, metric), (times, values) in vectors.items():
                if source + '.tcp.' in module and metric == 'rtt':
                    for offset in range(0, len(times), ARRAY_BLOCK):
                        t, v = times[offset:offset+ARRAY_BLOCK], values[offset:offset+ARRAY_BLOCK]
                        valid = (t >= start) & (t <= end) & np.isfinite(v) & (v > 0)
                        rtt_sum += float(np.sum(v[valid]))
                        rtt_count += int(np.count_nonzero(valid))
                        discard_pages(times)
                        discard_pages(values)
            row = dict(config=config['config'], protocol=config['protocol'], pair=config['pair'],
                k=config['k'], run=config['run'], **connection, goodput_mbps=mean,
                bytes_received=delivered, late_goodput_start=late,
                full_run_goodput_mbps=delivered * 8 / (config['sim_time'] - connection['start']) / 1e6,
                sender_rtt_ms=rtt_sum / rtt_count * 1000 if rtt_count else math.nan)
            series[f'connection_{index}_goodput_mbps'] = trace
            if connection['role'] == 'main':
                rank_availability, rank_plot = [], []
                for rank in range(1, config['k'] + 1):
                    prefix = source + f'.app[{rank}]'
                    def monitor(metric, times_grid):
                        matches = [v for (module, m), v in vectors.items() if module.endswith(prefix) and m == metric]
                        if len(matches) != 1 or not len(matches[0][0]):
                            raise ValueError(f'Missing monitor {prefix}/{metric}')
                        times = matches[0][0]
                        if times[0] > start or times[-1] < end - .11:
                            raise ValueError(f'Monitor {prefix}/{metric} does not cover the measurement window')
                        return sample_hold(*matches[0], times_grid)
                    available = monitor('kPathAvailable', path_grid)
                    if np.any(~np.isfinite(available)) or np.any((available != 0) & (available != 1)):
                        raise ValueError(f'Invalid availability for {prefix}')
                    expected = monitor('kPathExpectedRtt', path_grid)
                    valid = (available == 1) & np.isfinite(expected) & (expected >= 0)
                    paths.append(dict(config=config['config'], protocol=config['protocol'], pair=config['pair'],
                        k=config['k'], run=config['run'], connection=index, rank=rank,
                        available_pct=float(np.mean(available) * 100),
                        expected_rtt_ms=float(np.mean(expected[valid]) * 1000) if np.any(valid) else math.nan))
                    rank_availability.append(available)
                    rank_plot.append(monitor('kPathAvailable', grid + .000003))
                counts = np.sum(rank_availability, axis=0)
                availability.append(counts)
                row['mean_available_paths'] = float(np.mean(counts))
                row['all_k_available_pct'] = float(np.mean(counts == config['k']) * 100)
                series[f'connection_{index}_available_paths'] = np.sum(rank_plot, axis=0)
            connections.append(row)
        main = [r['goodput_mbps'] for r in connections if r['role'] == 'main']
        background = [r['goodput_mbps'] for r in connections if r['role'] == 'background']
        metadata = dict(config)
        raw_stat = raw.stat()
        summary = dict(metadata, raw_stat=[raw_stat.st_size, raw_stat.st_mtime_ns],
            main_total_mbps=sum(main), main_mean_mbps=float(np.mean(main)),
            main_jain=jain(main), all_connections_jain=jain(main + background),
            background_total_mbps=sum(background),
            mean_available_paths=float(np.mean(availability)),
            all_main_k_available_pct=float(np.mean(np.all(np.asarray(availability) == config['k'], axis=0)) * 100))
        write_csv(out / 'connections.csv', list(connections[0]), connections)
        write_csv(out / 'paths.csv', list(paths[0]), paths)
        np.savetxt(out / 'timeseries.csv', np.column_stack(list(series.values())), delimiter=',',
                   header=','.join(series), comments='', fmt='%.12g')
        # Preserve every original connection/thread ID for recovery and HoL inspection.
        for (module, metric), (times, values) in vectors.items():
            name = re.sub(r'[^A-Za-z0-9_.\[\]-]', '_', f'{module}__{metric}') + '.csv'
            with (out / name).open('w') as handle:
                handle.write('time,value\n')
                for offset in range(0, len(times), ARRAY_BLOCK):
                    np.savetxt(handle, np.column_stack((times[offset:offset+ARRAY_BLOCK],
                        values[offset:offset+ARRAY_BLOCK])), delimiter=',', fmt='%.12g')
                    discard_pages(times)
                    discard_pages(values)
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def extract_results(configs, cores=1):
    summaries = run_parallel(extract_config, configs, extraction_workers(cores, len(configs)))
    directory = experiment_directory(configs[0]['experiment']) / 'csvs'
    write_csv(directory / 'summary.csv', list(summaries[0]), summaries)
    print(f'Extracted {len(summaries)} runs to {directory}')


def plot_pair(job):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    experiment, pair, summaries, output = job
    output = Path(output)
    metrics = [('main_mean_mbps', 'Mean goodput per main connection (Mbps)'),
               ('main_jain', 'Jain fairness between main connections'),
               ('mean_available_paths', 'Mean available ranks per main connection'),
               ('background_total_mbps', 'Total background goodput (Mbps)')]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.5), constrained_layout=True)
    data = []
    for ax, (metric, label) in zip(axes.flat, metrics):
        for protocol in PROTOCOL_ORDER:
            means, deviations = [], []
            for k in range(1, 6):
                values = [s[metric] for s in summaries if s['protocol'] == protocol and s['k'] == k
                          and math.isfinite(s[metric])]
                mean = float(np.mean(values)) if values else math.nan
                std = float(np.std(values, ddof=1)) if len(values) > 1 else 0 if values else math.nan
                means.append(mean)
                deviations.append(std)
                data.append(dict(pair=pair, protocol=protocol, k=k, metric=metric, n=len(values), mean=mean, std=std))
            ax.errorbar(range(1, 6), means, yerr=deviations, marker='o', capsize=3,
                        label=CC_LABELS[protocol], color=CC_COLORS[protocol])
        ax.set(xlabel='Requested subflows per main connection', ylabel=label, xticks=range(1, 6))
        ax.grid(alpha=.2)
        if metric == 'main_jain':
            ax.set_ylim(0, 1.05)
        elif metric == 'mean_available_paths':
            ax.set_ylim(0, 5.2)
        else:
            ax.set_ylim(bottom=0)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(f'Experiment {experiment}: {pair} (mean ± sample SD)')
    for extension in ('png', 'pdf'):
        fig.savefig(output / f'{pair}.{extension}', dpi=160)
    plt.close(fig)
    return data


def plot_results(configs, cores=1):
    directory = experiment_directory(configs[0]['experiment']) / 'csvs'
    summaries = []
    for config in configs:
        path = directory / 'extracted' / config['config'] / 'summary.json'
        if not path.is_file():
            continue
        summary = json.loads(path.read_text())
        raw = directory / 'raw' / f'{config["config"]}.csv'
        if any(summary.get(key) != value for key, value in config.items()):
            raise ValueError(f'Stale extraction for {config["config"]}; run step 3')
        if not raw.is_file() or summary.get('raw_stat') != [raw.stat().st_size, raw.stat().st_mtime_ns]:
            raise ValueError(f'Stale raw data for {config["config"]}; run step 3')
        summaries.append(summary)
    if not summaries:
        raise ValueError('No extracted results to plot')
    output = SIMULATIONS_DIR / 'plots' / f'experiment{configs[0]["experiment"]}'
    output.mkdir(parents=True, exist_ok=True)
    jobs = [(configs[0]['experiment'], pair, [s for s in summaries if s['pair'] == pair], str(output))
            for pair, *_ in PAIRS if any(s['pair'] == pair for s in summaries)]
    data = [row for rows in run_parallel(plot_pair, jobs, cores) for row in rows]
    write_csv(output / 'plot_data.csv', list(data[0]), data)
    print(f'Plotted {len(jobs)} city pairs to {output}')
