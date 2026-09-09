#!/usr/bin/env python3
"""Experiment 2 topology with two temporary waves of fixed MPORB competitors."""
from pathlib import Path
import math
import sys
import xml.etree.ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / 'experiment2'))
import generateExperiment2IniFiles as base

EXPERIMENT_DIR = SCRIPT_DIR.parents[1] / 'experiments' / 'experiment5'
# (physical path, first background host, start, stop); path numbers are one-based.
WAVES = ((5, 0, 30, 60), (6, 5, 30, 60), (1, 10, 90, 120), (2, 15, 90, 120))
PROTOCOLS = base.PROTOCOLS
RUNS = base.RUNS
PATH_MBPS = 100
PATH_RTT_MS = base.PATH_RTT_MS
MSS_BYTES = base.MSS_BYTES


def bdp_packets():
    return math.ceil(PATH_MBPS * 1_000_000 * (PATH_RTT_MS / 1000) / (MSS_BYTES * 8))


def background_settings():
    lines = ['*.scenarioManager.script = xmldoc("conditions.xml")']
    for host in ('backgroundClient', 'backgroundServer'):
        lines += [
            f'*.{host}[*].numApps = 1',
            f'*.{host}[*].app[0].numberOfSubflows = 1',
            f'*.{host}[*].tcp.conn-*.numberOfSubflows = 1',
            f'*.{host}[*].tcp.typename = "MpOrb"',
            f'*.{host}[*].tcp.tcpAlgorithmClass = "MpOrbUncoupled"',
        ]
    lines += [
        '*.backgroundClient[*].app[0].typename = "MpTcpSessionApp"',
        '*.backgroundClient[*].app[0].connectPort = 1000',
        '*.backgroundClient[*].app[0].tClose = 151s',
        '*.backgroundClient[*].app[0].sendBytes = 1MiB',
        '*.backgroundClient[*].app[0].dataTransferMode = "bytecount"',
        '*.backgroundClient[*].tcp.initialSsthresh = 40000',
        '*.backgroundServer[*].app[0].typename = "MpTcpSinkApp"',
        '*.backgroundServer[*].app[0].localPort = 1000',
        '*.backgroundServer[*].app[0].serverThreadModuleType = "tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread"',
    ]
    for path, first, start, stop in WAVES:
        for i in range(first, first + 5):
            lines += [
                f'*.backgroundClient[{i}].app[0].connectAddress = "backgroundServer[{i}]"',
                f'*.backgroundClient[{i}].tcp.subflowRemoteAddresses = "backgroundServer[{i}]>router2[{path-1}]"',
                f'*.backgroundClient[{i}].app[0].tOpen = {start}s',
                f'*.backgroundClient[{i}].app[0].tSend = {start}s',
            ]
    return lines


def main():
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    general = []
    base.write_common_general(general.append)
    general = [s.replace('experiments.experiment2', 'experiments.experiment5')
               .replace('sim-time-limit = 40s', 'sim-time-limit = 150s')
               .replace('experiment2Log', 'experiment5Log')
               .replace('tClose = -1s', 'tClose = 151s')
               .replace('sendBytes = 2GB', 'sendBytes = 1MiB') for s in general]
    for i, line in enumerate(general):
        if line.startswith('**.ppp[*].queue.packetCapacity ='):
            general[i] = f'**.ppp[*].queue.packetCapacity = {bdp_packets()}'
        elif line.startswith('# All eight paths are'):
            general[i] = f'# All eight paths are {PATH_RTT_MS} ms / {PATH_MBPS} Mbps with one-BDP ({bdp_packets()} packet) queues.'
        elif line.startswith('# Enter congestion avoidance at'):
            general[i] = '# Foreground initialSsthresh is retained from experiment 2.'
    # Specific background overrides must precede general wildcard assignments.
    general[1:1] = background_settings()
    for protocol, settings in PROTOCOLS.items():
        lines = list(general)
        # Backgrounds always use MPORB, including in LIA/OLIA/BALIA comparisons.
        # Preserve experiment 2's bottleneck PPP indices by appending access links.
        for path in range(8):
            gate = 2 if path < 4 else 1
            lines.append(f'**.router1[{path}].ppp[{gate}].queue.typename = "PintQueue"')
        lines += [
            f'**.tcp.typename = "{settings["tcp_type"]}"',
            f'**.tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"',
            '**.ppp[*].queue.typename = "DropTailQueue"',
            '**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"',
            '**.additiveIncreasePercent = 0.05', '**.eta = 0.95',
            '**.alpha = 0.03', '**.fixedAvgRTTVal = 0s', '',
        ]
        for run in RUNS:
            def write(line=''):
                lines.append(line)
            base.write_config(write, settings, run)
        (EXPERIMENT_DIR / f'experiment5_{protocol}.ini').write_text('\n'.join(lines) + '\n')
    scenario = ET.Element('scenario')
    for stop in (60, 120):
        event = ET.SubElement(scenario, 'at', t=f'{stop}s')
        for path, first, start, end in WAVES:
            if end == stop:
                for i in range(first, first + 5):
                    ET.SubElement(event, 'set-param', module=f'backgroundClient[{i}].tcp',
                                  par='sendingEnabled', value='false')
    ET.indent(scenario)
    ET.ElementTree(scenario).write(EXPERIMENT_DIR / 'conditions.xml', encoding='unicode')
    print(f'Generated experiment 5: {len(PROTOCOLS)} protocols × 5 runs; 150s.')


if __name__ == '__main__':
    main()
