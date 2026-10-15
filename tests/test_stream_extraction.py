"""Small synthetic regression tests; no simulation results are read."""
import csv
import io
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'simulations/pythonScripts'
sys.path.insert(0, str(ROOT))
import streamScaveCsv as stream
import extractionResources as resources


class ExtractionTests(unittest.TestCase):
    def test_csv_quote_and_chunk_boundaries(self):
        rng=random.Random(4)
        rows=[['type','module','name','vectime','vecvalue']]
        rows += [[''.join(rng.choices('abc,\n\r" ',k=30)) for _ in range(5)] for _ in range(15)]
        output=io.StringIO(newline='');csv.writer(output).writerows(rows)
        for size in (1,2,3,7,31,1024):
            actual=[];row=[];field=bytearray()
            with patch.object(stream,'BLOCK_BYTES',size):
                for data,end,endrow in stream.field_parts(io.BytesIO(output.getvalue().encode())):
                    field.extend(data)
                    if end:row.append(field.decode());field.clear()
                    if endrow:actual.append(row);row=[]
            self.assertEqual(rows,actual)

    def extract(self, header, rows, metrics={'goodput'}):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);source=root/'raw.csv'
        with source.open('w',newline='') as f:
            w=csv.writer(f);w.writerow(header);w.writerows(rows)
        result=stream.extract_vectors(source,root/'out',metrics)
        return result,root/'out'

    def test_wide_selection_precision_and_collision(self):
        count,out=self.extract(['type','module','name','vectime','vecvalue'],[
            ['vector','n.app.thread_1','goodput:vector','0 1','1 2'],
            ['vector','n.app.thread_2','goodput:vector','0 1 2','1e-30 nan 1.234567890123456789'],
            ['vector','n.app','cwnd:vector','0 1','garbage not-numeric'],
            ['scalar','n.app','goodput','0','123'],
        ])
        self.assertEqual(count,2)
        self.assertEqual((out/'n.app/goodput.csv').read_text(), 'time,goodput\n0,1e-30\n1,nan\n2,1.234567890123456789\n')
        self.assertFalse((out/'n.app/cwnd.csv').exists())
        self.assertFalse(list(out.glob('.extract-*')))

    def test_no_type_reordered_fields_comma_arrays_and_shorter_vector(self):
        count,out=self.extract(['vectime','vecvalue','name','module'],[
            ['0,1,2','3,4','goodput','n']])
        self.assertEqual(count,1)
        self.assertEqual((out/'n/goodput.csv').read_text(),'time,goodput\n0,3\n1,4\n')

    def test_long_interleaving_invalid_and_last_group_wins(self):
        count,out=self.extract(['type','module','name','time','value'],[
            ['vector','n.thread_1','goodput','0','2'],
            ['vector','other','goodput','0','4'],
            ['vector','n.thread_2','goodput','0','8'],
            ['vector','n.thread_1','goodput','1','3'],
            ['vector','n.thread_2','goodput','1','nan'],
            ['vector','n.thread_2','goodput','2','9'],
            ['vector','other','cwnd','1','5'],
        ])
        self.assertEqual(count,3)
        self.assertEqual((out/'n/goodput.csv').read_text(),'time,goodput\n0.0,8.0\n2.0,9.0\n')

    def test_empty_vector(self):
        count,out=self.extract(['module','name','vectime','vecvalue'],[['n','goodput','','']])
        self.assertEqual(count,0)
        self.assertFalse(list(out.rglob('*.csv')))

    def test_large_vector_across_blocks(self):
        count,out=self.extract(['module','name','vectime','vecvalue'],[
            ['n','goodput',' '.join(map(str,range(200000))), ' '.join(['1.2e-3']*200000)]])
        self.assertEqual(count,1)
        with (out/'n/goodput.csv').open() as f:
            self.assertEqual(sum(1 for _ in f),200001)

    def test_malformed_csv_fails_and_cleans_scratch(self):
        with self.assertRaises(ValueError):
            list(stream.field_parts(io.BytesIO(b'a,"unterminated')))

    def test_all_cores_when_ram_permits(self):
        with patch.object(resources,'available_memory',return_value=32*resources.GiB),patch.dict(os.environ,{},clear=True):
            self.assertEqual(resources.extraction_workers(30,75),30)

    def test_memory_limit_not_fixed_cpu_cap(self):
        with patch.object(resources,'available_memory',return_value=4*resources.GiB),patch.dict(os.environ,{},clear=True):
            self.assertEqual(resources.extraction_workers(30,75),11)
        with patch.object(resources,'available_memory',return_value=resources.GiB),patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):resources.extraction_workers(30,75)

    def test_macos_excludes_swap_compressed_and_anon_inactive(self):
        text='Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\nFile-backed pages: 200.\nPages inactive: 50000.\nPages occupied by compressor: 100000.\n'
        with patch.object(resources.platform,'system',return_value='Darwin'),patch.object(resources.subprocess,'check_output',return_value=text):
            self.assertEqual(resources.available_memory(),300*16384)


if __name__ == '__main__':unittest.main()
