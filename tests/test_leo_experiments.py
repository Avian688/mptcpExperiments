"""Synthetic traffic/accounting tests; never runs a simulation or reads real results."""
import csv
import configparser
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'simulations/pythonScripts'
sys.path.insert(0, str(SCRIPTS))
import leoExperiments as experiments
import leoResults as results


class LeoExperimentsTests(unittest.TestCase):
    def test_matrix_and_independent_terminal_pairs(self):
        matrices = [experiments.configurations(n) for n in (8, 9, 10)]
        for matrix, count in zip(matrices, (1, 2, 7)):
            self.assertEqual(len(matrix), 300)
            self.assertEqual(len({c['config'] for c in matrix}), 300)
            self.assertEqual({c['protocol'] for c in matrix}, set(experiments.PROTOCOL_ORDER))
            self.assertEqual({(c['source_city'], c['destination_city']) for c in matrix}, {
                ('London', 'New York'), ('San Diego', 'Shanghai'), ('San Diego', 'Seattle')})
            self.assertEqual({c['run'] for c in matrix}, set(range(1, 6)))
            for config in matrix:
                self.assertEqual(len(config['connections']), count)
                terminals = [c[key] for c in config['connections'] for key in ('source', 'destination')]
                self.assertEqual(len(terminals), len(set(terminals)))
                for connection in config['connections']:
                    self.assertEqual(connection['subflows'], config['k'] if connection['role'] == 'main' else 1)
                    if connection['role'] == 'main':
                        self.assertEqual(experiments.endpoint_pairs(config['experiment'])[connection['path_group']],
                                         (connection['source'], connection['destination']))
        for configs in zip(*matrices):
            self.assertEqual(len({c['seed'] for c in configs}), 1)
            self.assertEqual(len({c['connections'][0]['start'] for c in configs}), 1)

    def test_shared_catalog_geometry(self):
        for number, terminals in ((8, 2), (9, 4), (10, 14)):
            text = experiments.network_text(number)
            self.assertIn(f'**.numOfUserTerminals = {terminals}\n', text)
            self.assertIn('kPathSnapshotSet = "ExperimentKShortestPaths"', text)
            self.assertIn(f'kPathCoreSnapshotProfile = "{experiments.core_snapshot_profile()}"', text)
            self.assertIn(f'kPathEndpointPairs = "{experiments.pair_specification(number)}"', text)
            self.assertEqual(experiments.pair_specification(number).count(','), 0 if number == 8 else 1)
            self.assertEqual(text.count('.mobility.latitude = '),
                             len(experiments.catalog.CITY_COORDINATES) + len(experiments.catalog.load_ground_stations()))
        for duration in (0, 19, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                experiments.configurations(8, duration)

    def test_generated_configs_place_only_active_terminals_at_selected_cities(self):
        with tempfile.TemporaryDirectory() as temporary:
            for number in (8, 9, 10):
                root = Path(temporary) / str(number)
                with patch.object(experiments, 'experiment_directory', return_value=root):
                    configs = experiments.generate(number)
                ini = configparser.ConfigParser(interpolation=None, strict=False)
                ini.read(root / f'experiment{number}.ini')
                self.assertEqual(int(ini['General']['**.numOfUserTerminals']), 2 * experiments.CONNECTION_COUNTS[number])
                for config in configs:
                    section = ini[f'Config {config["config"]}']
                    for connection in config['connections']:
                        for terminal, city in ((connection['source'], config['source_city']),
                                               (connection['destination'], config['destination_city'])):
                            for coordinate, value in zip(('latitude', 'longitude'), experiments.catalog.CITY_COORDINATES[city]):
                                self.assertEqual(float(section[f'*.userTerminal[{terminal}].mobility.{coordinate}']), value)

    def test_all_suites_reuse_the_original_saved_profile(self):
        for number in (8, 9, 10):
            backend = experiments.configure_runner(number)
            self.assertEqual(backend.PAIR_DEFINITIONS, experiments.catalog.PAIR_DEFINITIONS)
            _, paths = backend.route_directories()
            self.assertEqual(paths.name, experiments.core_snapshot_profile())
            self.assertEqual(paths.parent.name, 'ExperimentKShortestPaths')

    def write_raw(self, path, config, omit_receiver=False):
        rows = []
        rates = [10, 20, 1, 2, 3, 4, 5]
        for connection, rate in zip(config['connections'], rates):
            destination = f'n.userTerminal[{connection["destination"]}].app[0]'
            if not (omit_receiver and connection['index'] == 1):
                rows.append(['scalar', destination, 'bytesRcvd', str(rate * 1000000), '', ''])
            rows.append(['vector', destination + '.thread_99', 'goodput:vector', '', '0 10 19 20', ' '.join([str(rate * 1e6)] * 4)])
            if connection['role'] == 'main':
                for rank in (1, 2):
                    source = f'n.userTerminal[{connection["source"]}].app[{rank}]'
                    rows.append(['vector', source, 'kPathAvailable:vector', '', '0 10 19 20', '1 1 1 1' if rank == 1 else '0 0 0 0'])
                    rows.append(['vector', source, 'kPathExpectedRtt:vector', '', '0 10 19 20', '.04 .04 .04 .04' if rank == 1 else '-1 -1 -1 -1'])
        with path.open('w', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['type', 'module', 'name', 'value', 'vectime', 'vecvalue'])
            writer.writerows(rows)

    def test_seven_connections_goodput_and_missing_rank(self):
        config = next(c for c in experiments.configurations(10, 20) if c['k'] == 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / 'csvs/raw'
            raw.mkdir(parents=True)
            path = raw / f'{config["config"]}.csv'
            self.write_raw(path, config)
            with patch.object(results, 'experiment_directory', return_value=root):
                summary = results.extract_config(config)
                self.assertEqual(summary['main_total_mbps'], 30)
                self.assertEqual(summary['background_total_mbps'], 15)
                self.assertAlmostEqual(summary['main_jain'], .9)
                self.assertEqual(summary['mean_available_paths'], 1)
                self.assertEqual(summary['all_main_k_available_pct'], 0)
                self.assertTrue((root / 'csvs/extracted' / config['config'] / 'connections.csv').is_file())
                self.write_raw(path, config, omit_receiver=True)
                with self.assertRaisesRegex(ValueError, 'receiver scalar'):
                    results.extract_config(config)

    def test_zero_goodput_does_not_imply_perfect_fairness(self):
        self.assertNotEqual(results.jain([0, 0]), results.jain([0, 0]))
        self.assertAlmostEqual(results.jain([10, 10]), 1)


if __name__ == '__main__':
    unittest.main()
