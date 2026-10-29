#!/usr/bin/env python3
"""Configuration, topology and synthetic plotting checks; no simulations."""
import configparser
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simulations/pythonScripts'))
import redistributionExperiments as spec
import plotRedistribution as plots
from experimentProtocols import PROTOCOLS, SHUFFLE_PROTOCOLS

class Redistribution(unittest.TestCase):
    def test_inputs_and_pairing(self):
        for number in (6,7):
            with tempfile.TemporaryDirectory() as temp:
                spec.generate(number,temp);directory=Path(temp)
                paired={}
                for protocol,(_,algorithm,_) in PROTOCOLS.items():
                    ini=configparser.ConfigParser(interpolation=None,delimiters=('=',));ini.optionxform=str
                    ini.read(directory/f'experiment{number}_{protocol.lower()}.ini');g=ini['General']
                    self.assertEqual(g['**.tcp.tcpAlgorithmClass'],f'"{algorithm}"')
                    self.assertEqual(g['**.vector-recording'],'false')
                    self.assertEqual(g['**.schedulerMode'],'"defaultCwnd"')
                    self.assertEqual(g['*.linkCapacity'],'100Mbps')
                    self.assertEqual(g['*.pathRtt'],'20ms')
                    self.assertEqual(g['**.ppp[*].queue.packetCapacity'],'173')
                    self.assertNotIn('**.statistic-recording',g)
                    for interface,_ in spec.forward_interfaces(number):
                        q=f'*.{interface}.queue'
                        expected='MpOrbDeltaQueue' if protocol in SHUFFLE_PROTOCOLS else 'PintQueue'
                        self.assertEqual(g[q+'.typename'],f'"{expected}"')
                        if protocol in SHUFFLE_PROTOCOLS:self.assertEqual(g[q+'.deltaShuffleFraction'],'0.05')
                    positive=[k for k,v in g.items() if k.endswith('.deltaShuffleFraction') and v!='0']
                    self.assertEqual(len(positive),len(spec.forward_interfaces(number)) if protocol in SHUFFLE_PROTOCOLS else 0)
                    for case in spec.cases(number):
                        events=ET.parse(directory/f'{case.lower()}.xml').getroot()
                        stops={(p.attrib['module'],float(at.attrib['t'][:-1])) for at in events for p in at}
                        self.assertEqual(stops,{(f'client[{i}].tcp',float(end)) for i,_,end in spec.waves(number,case)})
                        for run in spec.RUNS:
                            section=ini[f'Config {protocol}_{case}_Run{run}']
                            starts=tuple(section[f'*.client[{i}].app[0].tSend'] for i in range(4))
                            if (case,run) in paired:self.assertEqual(starts,paired[case,run])
                            paired[case,run]=starts
                            for i,start,_ in spec.waves(number,case):self.assertEqual(float(section[f'*.client[{i}].app[0].tSend'][:-1]),start)
                    self.assertEqual(len(ini.sections()),1+5*len(spec.cases(number)))

    def test_core_gate_indices_and_edge_disjoint_paths(self):
        for n in (6,7):
            text=spec.network(n); gates=[0]*8;actual=[]
            for a,b in re.findall(r'router\[(\d+)\]\.pppg\+\+ <--> DatarateChannel.*?<--> router\[(\d+)\]\.pppg\+\+',text):
                a,b=int(a),int(b);actual.append(f'router[{a}].ppp[{gates[a]}]');gates[a]+=1;gates[b]+=1
            self.assertEqual(actual,[p for p,_ in spec.forward_interfaces(n)])
            links=spec.topology(n)[0]
            for alternatives in spec.topology(n)[1][:4]:
                paths=[{(a,b) for a,b in links if first<=a<b<=last} for first,last in alternatives]
                self.assertTrue(all(paths))
                if len(paths)==2:self.assertFalse(paths[0]&paths[1])

    def test_ideal_allocations_fit_link_capacities(self):
        # Explicit feasible allocations, in Mbps. Chain background forces each
        # successive connection onto its alternative: A(20,60), B(40,40), C(60,20).
        self.assertEqual(spec.reference(6,'Chain',40),(80.,)*4)
        np.testing.assert_allclose([80+20,60+40,40+60,20+80],[100]*4)
        # Parking backgrounds fill one middle link at 20 each. Spine/Rib2 use
        # the other middle link at 50 each; outer ribs use 100+50 across lanes.
        self.assertEqual(spec.reference(7,'LaneShift',40),(50.,150.,50.,150.))
        np.testing.assert_allclose([100,5*20,100,50+50,50+50,50+50],[100]*6)

    def test_busy_integration_and_unknown_rates(self):
        series=(np.array([.1,.3,.7,.9]),np.array([1,0,1,0]))
        np.testing.assert_allclose(plots.bin_busy(series,np.array([0.,.5,1.])),[.4,.4])
        self.assertTrue(np.isnan(plots.bin_busy((np.array([]),np.array([])),np.array([0.,1.]))).all())
        self.assertTrue(np.isnan(plots.sample((np.array([1.]),np.array([10.])),np.array([2.]),True)[0]))

    def test_full_synthetic_plot_pipeline(self):
        for n,case in ((6,'Chain'),(7,'LaneShift')):
            with tempfile.TemporaryDirectory() as temp:
                base=Path(temp);root=base/'csvs'/'Theta'/case.lower()/'run1'
                times=np.arange(.5,150.5,.5)
                def write(module,metric,t,v):
                    d=root/f'redistribution.{module}';d.mkdir(parents=True,exist_ok=True)
                    pd.DataFrame({'time':t,metric:v}).to_csv(d/f'{metric}.csv',index=False)
                for i,alternatives in enumerate(spec.topology(n)[1]):
                    write(f'server[{i}].app[0]','goodput',times,np.full_like(times,50e6))
                    for j,_ in enumerate(alternatives):
                        write(f'client[{i}].ppp[{j}].ppp','transmissionState',[0,1,2,149],[0,1,0,0])
                        for metric,value in [('cwnd',100000),('U',.95),('subflowSendQueueBytes',1000)]:
                            write(f'client[{i}].tcp.conn-{10+j}',metric,[0,150],[value,value])
                    write(f'server[{i}].tcp.conn-1','holBlockedBytes',[0,150],[0,0])
                for interface,_ in spec.forward_interfaces(n):write(interface+'.ppp','transmissionState',[0,1,149],[0,1,0])
                args=['plot','--configs',f'Theta_{case}','--runs','1','--csv-root',str(base/'csvs'),'--out-dir',str(base/'plots')]
                with patch.object(sys,'argv',args):self.assertEqual(plots.main(n),0)
                output=base/'plots'/'Theta'/case.lower()/'run1'
                for name in ('goodput','subflow_rates','link_utilisation','cwnd','U','holBlockedBytes'):
                    self.assertGreater((output/f'{name}.png').stat().st_size,1000)
                frame=pd.read_csv(base/'plots/phase_summary.csv')
                self.assertEqual(set(frame.connection),set(spec.topology(n)[2]))
                np.testing.assert_allclose(frame.goodput_mbps,50)

if __name__=='__main__':unittest.main()
