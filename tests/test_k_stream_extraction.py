"""Synthetic K-path extraction checks; no existing results are read."""
import csv
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'simulations/pythonScripts'
sys.path.insert(0, str(SCRIPTS / 'experimentMpOrbKShortestPaths'))
spec = importlib.util.spec_from_file_location('k_extract', SCRIPTS / 'experimentMpOrbKShortestPaths/extractSingleCsvFile.py')
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


class KExtractionTests(unittest.TestCase):
    def write(self, path, rows):
        with path.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['type', 'module', 'name', 'value', 'vectime', 'vecvalue'])
            w.writerows(rows)

    def test_disk_backed_vectors_scalars_and_empty_vectors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write(root/'in.csv', [
                ['scalar', 'n', 'bytesRcvd', '50', '', ''],
                ['vector', 'n', 'goodput:vector', '', '0 1 2', '3 4 5'],
                ['vector', 'n', 'empty:vector', '', '', ''],
            ])
            vectors, scalars = k.read_csv_file(root/'in.csv', root)
            times, values = vectors['n', 'goodput']
            self.assertIsInstance(times, np.memmap)
            np.testing.assert_array_equal(values, [3,4,5])
            self.assertEqual(scalars['n','bytesRcvd'], 50)
            self.assertEqual(len(vectors['n','empty'][0]), 0)
            k.discard_pages(times)
            np.testing.assert_array_equal(times, [0,1,2])

    def test_invalid_lengths_order_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for times, values in [('0 1', '5'), ('0 2 1', '4 5 6')]:
                self.write(root/'in.csv', [['vector','n','v','', times, values]])
                with self.assertRaises(ValueError):
                    k.read_csv_file(root/'in.csv', root)
            self.write(root/'in.csv', [['vector','n','v','','0','1']]*2)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                k.read_csv_file(root/'in.csv', root)

    def test_chunked_integral(self):
        times = np.arange(150000) / 100
        values = np.arange(150000) % 137
        widths = np.maximum(0, np.minimum(times[1:], 800.3)-np.maximum(times[:-1], 12.4))
        expected = float(np.sum(widths * values[1:]))
        self.assertAlmostEqual(k.interval_rate_integral(times, values, 12.4, 800.3), expected, places=8)

    def test_full_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'raw').mkdir()
            self.write(root/'raw/test.csv', [
                ['scalar','n.userTerminal[1].app[0]','bytesRcvd','5000000','',''],
                ['vector','n.userTerminal[1].app[0].thread_3','goodput:vector','','0 1 2 3 4','10000000 10000000 10000000 10000000 10000000'],
                ['vector','n.userTerminal[0].app[1]','kPathAvailable:vector','','0 1 2 3 4','1 1 1 1 1'],
                ['vector','n.userTerminal[0].app[1]','kPathExpectedRtt:vector','','0 1 2 3 4','.04 .04 .04 .04 .04'],
                ['vector','n.userTerminal[0].tcp.conn-1','rtt:vector','','0 1 2 3 4','.04 .04 .04 .04 .04'],
            ])
            config=dict(config='test', destination=1, source=0, measurement_start=1., measurement_end=4., sim_time=5., start=0., k=1, protocol='Alpha', batch='alpha', pair='a-b', run=1)
            with patch.object(k, 'CSV_DIR', root):
                summary, paths = k.extract_config(config)
            self.assertAlmostEqual(summary['goodput_mbps'], 10)
            self.assertAlmostEqual(summary['sender_rtt_ms'], 40)
            self.assertEqual(summary['all_k_available_pct'], 100)
            self.assertAlmostEqual(paths[0]['expected_rtt_ms'], 40)
            self.assertTrue((root/'extracted/test/timeseries.csv').exists())
            self.assertTrue((root/'extracted/test/summary.json').exists())


if __name__ == '__main__':
    unittest.main()
