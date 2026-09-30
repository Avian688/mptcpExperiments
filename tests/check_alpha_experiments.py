#!/usr/bin/env python3
"""Static/configuration and synthetic-data checks; never starts a simulation."""
import argparse
import configparser
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'simulations/pythonScripts'))
import alphaValidation as spec
import plotAlphaValidation as plots
import runAlphaValidation as runner


def parse_ini(path):
    config = configparser.ConfigParser(interpolation=None, delimiters=('=',))
    config.optionxform = str
    config.read(path)
    return config


class AlphaExperiments(unittest.TestCase):
    def test_alpha_beta_pairing_and_separate_outputs(self):
        for number, count in ((5, 10), (6, 30)):
            definitions = spec.cases(number)
            self.assertEqual(len(definitions) * 5, count)
            self.assertEqual(len({slug for _, slug, _ in definitions}), len(definitions))
            directory = ROOT / f'simulations/experiments/experiment{number}'
            alpha = parse_ini(directory / f'experiment{number}_mporb_alpha.ini')
            beta = parse_ini(directory / f'experiment{number}_mporb_beta.ini')
            self.assertEqual(beta['General']['**.tcp.tcpAlgorithmClass'], '"MpOrbSemiCoupledBeta"')
            for key, value in alpha['General'].items():
                if key != '**.tcp.tcpAlgorithmClass':
                    self.assertEqual(value, beta['General'][key], key)
            for section in alpha.sections():
                if section == 'General':
                    continue
                other = section.replace('Alpha_', 'Beta_')
                for key, value in alpha[section].items():
                    if key in ('description', 'output-vector-file', 'output-scalar-file'):
                        continue
                    self.assertEqual(value, beta[other][key], (section, key))
                self.assertNotEqual(alpha[section]['output-vector-file'], beta[other]['output-vector-file'])
            for metric in spec.BETA_METRICS:
                self.assertTrue(any(k.endswith(f'.{metric}:vector.vector-recording')
                                    for k in beta['General']), metric)

    def test_runner_defaults_include_both_protocols_without_launching(self):
        for number, count in ((5, 10), (6, 30)):
            with patch.object(sys, 'argv', ['runner', '--skip-generate', '--dry-run']), \
                    patch.object(runner, 'run_parallel') as launch, \
                    patch('builtins.print'):
                self.assertEqual(runner.main(number), 0)
            launch.assert_not_called()
            self.assertEqual(len(runner.CONFIGS) * 5, count)
            self.assertEqual({entry[2] for entry in runner.CONFIGS},
                             {f'experiment{number}_mporb_alpha.ini', f'experiment{number}_mporb_beta.ini'})

    def test_comparison_keeps_alpha_and_beta_measurements_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            times = np.arange(.5, 300.5, .5)
            for slug, value in (('fairness', 60.), ('beta_fairness', 40.)):
                for run in (1, 2):
                    for i in range(3):
                        folder = root / 'csvs' / slug / f'run{run}' / f'fairnessPaths.server[{i}].app[0]'
                        folder.mkdir(parents=True)
                        pd.DataFrame({'time': times, 'goodput': value * 1e6}).to_csv(folder/'goodput.csv', index=False)
            labels = []
            original_save = plots.save
            def capture(fig, path):
                if path.name == 'allocation_comparison':
                    labels.extend(fig.axes[0].get_legend_handles_labels()[1])
                original_save(fig, path)
            with patch.object(sys, 'argv', ['plot', '--runs', '1', '2', '--csv-root', str(root/'csvs'),
                                           '--out-dir', str(root/'plots')]), \
                    patch.object(plots, 'dashboard'), patch.object(plots, 'save', side_effect=capture):
                self.assertEqual(plots.main(5), 0)
            results = pd.read_csv(root/'plots/phase_runs.csv')
            self.assertEqual(set(results.protocol), {'Alpha', 'Beta'})
            self.assertEqual(results[results.protocol == 'Alpha'].A_final20s_mbps.mean(), 60.)
            self.assertEqual(results[results.protocol == 'Beta'].A_final20s_mbps.mean(), 40.)
            self.assertIn('Alpha', labels)
            self.assertIn('Beta', labels)
            self.assertTrue((root/'plots/allocation_comparison.png').exists())

    def test_matrix_and_background_scope(self):
        for number, count in ((1, 50), (5, 5), (6, 15)):
            path = ROOT / f'simulations/experiments/experiment{number}/experiment{number}_mporb_alpha.ini'
            ini = parse_ini(path)
            self.assertEqual(sum(s.startswith('Config ') for s in ini), count)
            self.assertEqual(ini['General']['**.tcp.tcpAlgorithmClass'], '"MpOrbSemiCoupledAlpha"')
            self.assertEqual(ini['General']['**.schedulerMode'], '"defaultCwnd"')
            self.assertNotIn('**.statistic-recording', ini['General'])
            for metric in spec.METRICS:
                keys = [k for k in ini['General'] if k.endswith(f'.{metric}:vector.vector-recording')]
                self.assertTrue(keys, metric)
                self.assertTrue(all(ini['General'][k] == 'true' for k in keys))
            self.assertNotIn('**.queueLength:vector.vector-recording', ini['General'])
        ini = parse_ini(ROOT / 'simulations/experiments/experiment1/experiment1_mporb_alpha.ini')
        self.assertEqual(ini['General']['*.path1Rtt'], '20ms')
        self.assertEqual(ini['General']['**.ppp[*].queue.packetCapacity'], '173')
        for rtt in range(20, 201, 20):
            for run in range(1, 6):
                section = ini[f'Config Alpha_Rtt20_{rtt}_Run{run}']
                self.assertEqual(section['*.path2Rtt'], f'{rtt}ms')
                for i in range(3, 7):
                    self.assertEqual(section[f'*.client[{i}].app[0].tSend'], '60.000000s')
        scenario = ET.parse(ROOT / 'simulations/experiments/experiment1/conditions.xml')
        event, = scenario.getroot()
        self.assertEqual(event.attrib['t'], '120s')
        self.assertEqual({p.attrib['module'] for p in event}, {f'client[{i}].tcp' for i in range(3, 7)})

    def test_arrival_order_preserves_pairing(self):
        ini = parse_ini(ROOT / 'simulations/experiments/experiment6/experiment6_mporb_alpha.ini')
        for run in range(1, 6):
            def starts(order):
                s = ini[f'Config Alpha_{order}_Run{run}']
                return [float(s[f'*.client[{i}].app[0].tOpen'][:-1]) for i in range(3)]
            a = starts('AFirst'); bc = starts('BCFirst')
            np.testing.assert_allclose(np.array(bc)-np.array(a), [60, -60, -60])
            self.assertEqual(len(set(starts('Together'))), 1)

    def test_reference_allocations_are_feasible(self):
        # Busy-path competition: A withdraws from link 2; five competitors fill it.
        a, b, c = spec.reference(1, 'Competition')
        self.assertEqual(a+b, 100)
        self.assertEqual(5*c, 100)
        # Serial-link topology: private 20 Mbps route full, shared rate z.
        for objective in ('pf', 'maxmin'):
            a, b, c = spec.reference(5, 'Steady topology', objective)
            z = a-20
            self.assertEqual(z+b, 100)
            self.assertEqual(z+c, 100)
            if objective == 'pf':
                self.assertAlmostEqual(1/a - 1/b - 1/c, 0)
            else:
                self.assertEqual(a, b)
                self.assertEqual(b, c)

    def test_plotting_does_not_invent_rate_tails_or_convergence(self):
        values = plots.sample((np.array([1., 1.5, 2.]), np.array([5., 0., 7.])),
                              np.array([.25, .75, 1.25, 1.75, 2.25]), True)
        np.testing.assert_allclose(values[1:4], [5, 0, 7])
        self.assertTrue(np.isnan(values[[0, 4]]).all())
        grid = np.arange(.25, 10, .5)
        self.assertTrue(np.isnan(plots.settling(np.ones((3, len(grid))), [50]*3, grid, 0, 10)))
        self.assertEqual(plots.settling(np.full((3, len(grid)), 50.), [50]*3, grid, 0, 10), 0)
        mean, variance, counts = plots.mean_variance(np.array([[1., np.nan], [3., 5.]]))
        np.testing.assert_allclose(mean, [2, 5])
        self.assertEqual(variance[0], 2)
        self.assertTrue(np.isnan(variance[1]))

    def test_resume_rejects_teardown_failure_and_changed_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            experiment = root / 'experiment'; experiment.mkdir()
            (experiment / 'test.ini').write_text('[General]\n')
            (experiment / 'test.ned').write_text('network Test {}\n')
            entry = runner.Entry('Alpha', 'test', 'test.ini', 1)
            args = argparse.Namespace(resume=True, sim_timeout_seconds=10, sim_time_limit=None)
            returns = [-6, 0, 0]
            called = []
            def fake_launch(command, cwd, log, timeout):
                called.append(command)
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text('Simulation time limit reached\nCalling finish() at end of Run\n')
                runner.expected_vec(entry).write_text('vector')
                runner.expected_sca(entry).write_text('scalar')
                return returns.pop(0), False
            with patch.multiple(runner, EXPERIMENT_DIR=experiment, RESULTS_DIR=experiment/'results',
                                LOG_DIR=root/'logs'), patch.object(runner, 'load_libs', return_value=[]), \
                    patch.object(runner, 'simulation_command', return_value=['mock-simulator']), \
                    patch.object(runner, 'run_logged_command', side_effect=fake_launch):
                self.assertFalse(runner.run_simulation(entry, args)[1])
                self.assertFalse(list((experiment/'results').glob('*.complete.json')))
                self.assertTrue(runner.run_simulation(entry, args)[1])
                self.assertTrue(runner.run_simulation(entry, args)[1])
                self.assertEqual(len(called), 2)  # third call resumed, not launched
                (experiment/'test.ini').write_text('[General]\nsim-time-limit = 999s\n')
                self.assertTrue(runner.run_simulation(entry, args)[1])
                self.assertEqual(len(called), 3)

    def test_retained_runners_point_to_existing_inis(self):
        for number in (2, 3, 4):
            path = ROOT / f'simulations/pythonScripts/experiment{number}/runExperiment{number}.py'
            module_spec = importlib.util.spec_from_file_location(f'retained{number}', path)
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_spec.name] = module
            module_spec.loader.exec_module(module)
            for config in module.CONFIGS:
                self.assertTrue((module.EXPERIMENT_DIR / config[2]).exists(), config[2])
            for ini in module.EXPERIMENT_DIR.glob('*.ini'):
                text = ini.read_text()
                for xml in re.findall(r'xmldoc\("([^"\)]+)"\)', text):
                    self.assertTrue((ini.parent/xml).exists(), str(ini.parent/xml))


if __name__ == '__main__':
    unittest.main()
