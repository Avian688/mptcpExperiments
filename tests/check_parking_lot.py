#!/usr/bin/env python3
"""Experiment 7 configuration, topology and synthetic plotting checks; no simulation."""
from collections import defaultdict, deque
import configparser
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'simulations/pythonScripts'
sys.path[:0] = [str(SCRIPTS / 'experiment7'), str(SCRIPTS)]
import parkingLot as spec
import plotExperiment7 as plots
import runAlphaValidation as runner
import extractAlphaValidation as extractor


class ParkingLot(unittest.TestCase):
    def test_generated_matrix_pairing_and_recording(self):
        with tempfile.TemporaryDirectory() as temp:
            spec.generate(directory=temp)
            paired = {}
            for protocol, (tcp, algorithm, _) in spec.PROTOCOLS.items():
                path = Path(temp) / spec.ini_name(protocol)
                self.assertEqual(path.read_bytes(), (spec.EXPERIMENT_DIR / path.name).read_bytes())
                ini = configparser.ConfigParser(interpolation=None, delimiters=('=',))
                ini.optionxform = str
                ini.read(path)
                general = ini['General']
                self.assertEqual(general['**.tcp.typename'], f'"{tcp}"')
                self.assertEqual(general['**.tcp.tcpAlgorithmClass'], f'"{algorithm}"')
                self.assertEqual(general['**.schedulerMode'], '"defaultCwnd"')
                self.assertEqual(general['**.fixedAvgRTTVal'], '0s')
                self.assertEqual(len(ini.sections()), 51)
                self.assertNotIn('**.statistic-recording', general)
                for host in spec.CLIENTS + spec.SERVERS:
                    self.assertEqual(general[f'*.{host}.app[0].numberOfSubflows'], '2')
                    self.assertEqual(general[f'*.{host}.tcp.conn-*.numberOfSubflows'], '2')
                self.assertEqual(sum(value == '"PintQueue"' for value in general.values()), 6)
                self.assertEqual(general['*.spineServer.app[0].**.goodput.result-recording-modes'], 'vector')
                for rtt in spec.RTTS_MS:
                    for run in spec.RUNS:
                        section = ini[f'Config {spec.prefix(protocol, rtt)}_Run{run}']
                        self.assertEqual(section['sim-time-limit'], f'{rtt * 2}s')
                        self.assertEqual(section['**.ppp[*].queue.packetCapacity'], str(spec.packet_capacity(rtt)))
                        starts = tuple(section[f'*.{host}.app[0].tSend'] for host in spec.CLIENTS)
                        if (rtt, run) in paired:
                            self.assertEqual(starts, paired[rtt, run])
                        paired[rtt, run] = starts
                        self.assertTrue(section['output-vector-file'].endswith('-#0.vec"'))
            self.assertEqual(spec.packet_capacity(20), 173)
            self.assertEqual(spec.packet_capacity(200), 1727)

    def test_parsed_ned_routes_and_actual_gate_allocation(self):
        tool = ROOT.parents[1] / 'bin/opp_nedtool'
        if not tool.exists():
            self.skipTest('opp_nedtool unavailable')
        with tempfile.TemporaryDirectory() as temp:
            ned = Path(temp) / 'topology.ned'
            shutil.copyfile(spec.EXPERIMENT_DIR / 'twoLaneParkingLot.ned', ned)
            subprocess.run([str(tool), 'c', '-x', str(ned)], check=True, capture_output=True)
            ast = ET.parse(str(ned) + '.xml').getroot()
            graph, gates = defaultdict(list), defaultdict(list)
            cores = []

            def connect(node, i=None):
                def endpoint(side):
                    name = node.get(f'{side}-module')
                    expr = node.get(f'{side}-module-index')
                    if expr is None:
                        return name
                    index = {'i': i, 'i+1': None if i is None else i + 1}.get(expr)
                    if index is None:
                        index = int(expr)
                    return f'{name}[{index}]'
                a, b = endpoint('src'), endpoint('dest')
                params = {p.get('name'): p.get('value') for p in node.findall('parameters/param')}
                if a.startswith('lane') and b.startswith('lane'):
                    self.assertEqual(a[:5], b[:5])
                    cores.append(f'{a}.ppp[{len(gates[a])}].queue')
                    self.assertEqual(params['datarate'], 'parent.linkCapacity')
                else:
                    self.assertEqual(params['delay'], 'parent.pathRtt / 4')
                    self.assertEqual(params['datarate'], '10Gbps')
                graph[a].append(b)
                graph[b].append(a)
                gates[a].append(b)
                gates[b].append(a)

            for node in ast.find('compound-module/connections'):
                if node.tag == 'connection':
                    connect(node)
                elif node.tag == 'connection-group':
                    loop = node.find('loop')
                    for i in range(int(loop.get('from-value')), int(loop.get('to-value')) + 1):
                        for connection in node.findall('connection'):
                            connect(connection, i)
            self.assertEqual(set(cores), {q for q, _ in spec.QUEUES})
            self.assertEqual(len(cores), 6)
            for client, server, links in zip(spec.CLIENTS, spec.SERVERS, (3, 1, 1, 1)):
                self.assertEqual(len(gates[client]), 2)
                self.assertEqual(len(gates[server]), 2)
                remote_line = next(line for line in spec.general('Alpha')
                                   if line.startswith(f'*.{client}.tcp.subflowRemoteAddresses ='))
                remotes = remote_line.split('=', 1)[1].strip().strip('"').split()
                self.assertEqual(remotes, [f'{server}>{router}' for router in gates[server]])
                routes = []
                for lane in range(2):
                    self.assertTrue(gates[client][lane].startswith(f'lane{lane}Router'))
                    self.assertTrue(gates[server][lane].startswith(f'lane{lane}Router'))
                    queue = deque([(gates[client][lane], [client, gates[client][lane]])])
                    while queue:
                        node, path = queue.popleft()
                        if node == server:
                            break
                        for other in graph[node]:
                            if other not in path and (other.startswith(f'lane{lane}Router') or other == server):
                                queue.append((other, path + [other]))
                    else:
                        self.fail(f'No lane {lane} path for {client}')
                    self.assertEqual(len(path) - 3, links)
                    routes.append({frozenset(edge) for edge in zip(path, path[1:])})
                self.assertFalse(routes[0] & routes[1])

    def test_dry_run_pipeline_selects_four_algorithms(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['run', '--dry-run', '--skip-generate', '--cores', '10']), \
                patch.object(runner, 'run_parallel', side_effect=AssertionError('Must not simulate')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(runner.main(7, configurations=spec.configurations(),
                                        generate_inputs=spec.generate,
                                        plot_script=SCRIPTS/'experiment7/plotExperiment7.py',
                                        extract_script=SCRIPTS/'experiment7/extractSingleCsvFile.py'), 0)
        commands = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('[')]
        self.assertEqual(len(commands), 200)
        self.assertEqual({cmd[cmd.index('-f') + 1] for cmd in commands},
                         {spec.ini_name(p) for p in spec.PROTOCOLS})
        self.assertEqual(len({cmd[cmd.index('-c') + 1] for cmd in commands}), 200)

    def test_extraction_preserves_subflows_and_periodic_zeros(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = []
            for conn in (10, 11):
                for metric in ('cwnd', 'rtt', 'subflowSendQueueBytes'):
                    records.append(dict(type='vector', module=f'twoLaneParkingLot.spineClient.tcp.conn-{conn}',
                                        name=f'{metric}:vector(removeRepeats)', vectime='0 1', vecvalue='1 2'))
            records.append(dict(type='vector', module='twoLaneParkingLot.spineServer.app[0].thread_50',
                                name='goodput:vector', vectime='1 2 3', vecvalue='100000000 0 100000000'))
            source = root/'export.csv'
            pd.DataFrame(records).to_csv(source, index=False)
            with patch.object(extractor, '__file__', str(root/'pythonScripts/extractAlphaValidation.py')), \
                    patch.object(sys, 'argv', ['extract', '7', str(source), 'Alpha/rtt20ms', '1']):
                self.assertEqual(extractor.main(metrics=spec.METRICS), 0)
            extracted = root/'experiments/experiment7/csvs/Alpha/rtt20ms/run1'
            self.assertEqual(len(list(extracted.glob('*/rtt.csv'))), 2)
            rates = pd.read_csv(extracted/'twoLaneParkingLot.spineServer.app[0]/goodput.csv')
            self.assertEqual(rates.goodput.tolist(), [1e8, 0, 1e8])

    def test_missing_rates_not_filled_and_fairness_references(self):
        grid = np.arange(.5, 40, 1)
        maxmin = np.full((4, len(grid)), 100.)
        pf = np.array([50, 150, 150, 150])[:, None] * np.ones(len(grid))
        self.assertAlmostEqual(plots.fairness_row(maxmin, grid, 20)['goodput_ratio'], 1)
        self.assertAlmostEqual(plots.fairness_row(pf, grid, 20)['goodput_ratio'], 1/3)
        maxmin[:, -1] = np.nan  # Real periodic timers stop before the time limit.
        self.assertAlmostEqual(plots.fairness_row(maxmin, grid, 20)['goodput_ratio'], 1)
        maxmin[0, -5] = np.nan  # An internal gap must not get the tail exemption.
        self.assertTrue(np.isnan(plots.fairness_row(maxmin, grid, 20)['goodput_ratio']))
        pf[0, -5:] = np.nan
        self.assertTrue(np.isnan(plots.fairness_row(pf, grid, 20)['goodput_ratio']))
        values = plots.sample((np.array([1., 2., 5.]), np.array([10., 0., 20.])),
                              np.array([.5, 1.5, 2.5, 4.5, 5.5]), True)
        np.testing.assert_allclose(values, [10, 0, np.nan, 20, np.nan], equal_nan=True)

    def test_one_run_comparison_has_unknown_variance(self):
        with tempfile.TemporaryDirectory() as temp:
            grid = np.arange(.5, 40, 1)
            row = dict(protocol='Alpha', rtt_ms=20, run=1,
                       **plots.fairness_row(np.full((4, 40), 100.), grid, 20))
            plots.comparisons(pd.DataFrame([row]), Path(temp))
            summary = pd.read_csv(Path(temp)/'summary.csv')
            self.assertEqual(summary.goodput_ratio_count.iloc[0], 1)
            self.assertTrue(np.isnan(summary.goodput_ratio_std.iloc[0]))

    def test_full_plot_path_with_all_four_protocols(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            inputs, output = base/'inputs', base/'plots'
            times = np.arange(1., 41.)
            def write(root, module, metric, value):
                path = root/f'twoLaneParkingLot.{module}'
                path.mkdir(parents=True, exist_ok=True)
                pd.DataFrame({'time': times, metric: value}).to_csv(path/f'{metric}.csv', index=False)
            for protocol in spec.PROTOCOLS:
                for run in (1, 2):
                    root = inputs/spec.slug(protocol, 20)/f'run{run}'
                    for i, (client, server) in enumerate(zip(spec.CLIENTS, spec.SERVERS)):
                        rate = (50 if i == 0 else 150) if protocol == 'Beta' else (96 if run == 1 else 104)
                        write(root, f'{server}.app[0]', 'goodput', rate * 1e6)
                        write(root, f'{server}.tcp.conn-1', 'holBlockedBytes', 1000.)
                        for conn in (2, 3):
                            write(root, f'{server}.tcp.conn-{conn}', 'throughput', rate * 1e6 / 2)
                            for metric, value in (('cwnd', 125000.), ('rtt', .02), ('subflowSendQueueBytes', 500.)):
                                write(root, f'{client}.tcp.conn-{conn}', metric, value)
                    for queue, _ in spec.QUEUES:
                        write(root, queue, 'queueLength', 2.)
            argv = ['plot', '--csv-root', str(inputs), '--out-dir', str(output), '--runs', '1', '2',
                    '--configs', *[spec.prefix(p, 20) for p in spec.PROTOCOLS]]
            with patch.object(sys, 'argv', argv):
                self.assertEqual(plots.main(), 0)
            summary = pd.read_csv(output/'summary.csv').set_index('protocol')
            self.assertEqual(len(summary), 4)
            self.assertAlmostEqual(summary.loc['Alpha', 'spine_goodput_mbps_mean'], 100.)
            self.assertAlmostEqual(summary.loc['Alpha', 'spine_goodput_mbps_std'], np.sqrt(32))
            self.assertAlmostEqual(summary.loc['Beta', 'goodput_ratio_mean'], 1/3)
            for name in ('goodput_ratio', 'goodput_by_rtt', 'Alpha/rtt20ms/goodput_mean_variance',
                         'Alpha/rtt20ms/run1/goodput', 'Alpha/rtt20ms/run1/cwnd',
                         'Alpha/rtt20ms/run1/rtt', 'Alpha/rtt20ms/run1/throughput',
                         'Alpha/rtt20ms/run1/queueLength', 'Alpha/rtt20ms/run1/transport'):
                for extension in ('png', 'pdf'):
                    self.assertGreater((output/f'{name}.{extension}').stat().st_size, 1000)

if __name__ == '__main__':
    unittest.main()
