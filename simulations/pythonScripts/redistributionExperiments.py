"""Experiments 6/7: fixed 100 Mbps, 20 ms paths and explicit traffic shifts."""
from pathlib import Path
import random
import xml.etree.ElementTree as ET
from alphaValidation import general as common_general
from experimentProtocols import PROTOCOLS, SHUFFLE_PROTOCOLS, shuffle_settings

SIM_ROOT = Path(__file__).resolve().parents[1]
RUNS = range(1, 6)
DURATION = 150
STEP = 0.5
CAPACITY_MBPS = 100
RTT_MS = 20
METRICS = ('goodput', 'throughput', 'cwnd', 'srtt', 'U', 'subflowSendQueueBytes',
           'holBlockedBytes', 'queueLength', 'pintLocalUtilization', 'transmissionState')


def topology(number):
    # Route = (first router, last router); alternatives are ordered by ppp index.
    if number == 6:
        links = [(2*i, 2*i+1) for i in range(4)]
        routes = [[links[0], links[1]], [links[1], links[2]],
                  [links[2], links[3]], [links[3]], [links[0]]]
        return links, routes, ('A', 'B', 'C', 'D')
    if number == 7:
        links = [(i, i+1) for i in (0, 1, 2, 4, 5, 6)]
        routes = [[(0, 3), (4, 7)]] + [[(i, i+1), (i+4, i+5)] for i in range(3)]
        routes += [[(1, 2)]] * 5 + [[(5, 6)]] * 5
        return links, routes, ('Spine', 'Rib 1', 'Rib 2', 'Rib 3')
    raise ValueError(number)


def cases(number):
    return ('Chain',) if number == 6 else ('Symmetric', 'LaneShift')


def waves(number, case):
    if number == 6:
        return [(4, 30, 90)]
    return [] if case == 'Symmetric' else [(i, 30, 60) for i in range(4, 9)] + [(i, 90, 120) for i in range(9, 14)]


def phases(number, case):
    if number == 6:
        return [(0, 30, 'Baseline'), (30, 90, 'L1 competition'), (90, 150, 'Recovery')]
    if case == 'Symmetric':
        return [(0, 150, 'Baseline')]
    return [(0, 30, 'Baseline'), (30, 60, 'Lane 1 competition'), (60, 90, 'Recovery 1'),
            (90, 120, 'Lane 2 competition'), (120, 150, 'Recovery 2')]


def reference(number, case, t):
    # Ideal connection max-min, without wire overhead/utilisation headroom.
    # Parking lot: five backgrounds freeze at 20 each on the affected link.
    # Spine+Rib2 then share the other middle link: 50 each; outer ribs get 150.
    if number == 6:
        return (80.,)*4 if 30 <= t < 90 else (100.,)*4
    if case == 'LaneShift' and (30 <= t < 60 or 90 <= t < 120):
        y = 50.
        return (y, 200-y, y, 200-y)
    return (100.,)*4


def configurations(number):
    return [(f'{p}_{case}', f'{p}/{case.lower()}', f'experiment{number}_{p.lower()}.ini')
            for p in PROTOCOLS for case in cases(number)]


def forward_interfaces(number):
    degree = [0]*8
    result = []
    for i, (a, b) in enumerate(topology(number)[0]):
        label = f'L{i+1}' if number == 6 else f'Lane {i//3+1}, link {i%3+1}'
        result.append((f'router[{a}].ppp[{degree[a]}]', label))
        degree[a] += 1
        degree[b] += 1
    return result


def network(number):
    links, routes, _ = topology(number)
    lines = [f'package mptcpexperiments.simulations.experiments.experiment{number};',
             '@namespace(inet);', 'import inet.node.inet.StandardHost;',
             'import inet.node.inet.Router;', 'import ned.DatarateChannel;',
             'import inet.common.scenario.ScenarioManager;',
             'import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;',
             'network redistribution', '{', '    parameters:',
             '        double pathRtt @unit(s) = default(20ms);',
             '        double linkCapacity @unit(bps) = default(100Mbps);',
             '    submodules:', f'        client[{len(routes)}]: StandardHost;',
             f'        server[{len(routes)}]: StandardHost;',
             '        router[8]: Router;', '        configurator: AutoNetworkConfigurator;',
             '        scenarioManager: ScenarioManager;', '    connections:']
    # Allocate all core PPP gates first; forward_interfaces follows this order.
    for a, b in links:
        lines.append(f'        router[{a}].pppg++ <--> DatarateChannel {{ datarate = parent.linkCapacity; delay = 0s; }} <--> router[{b}].pppg++;')
    for i, alternatives in enumerate(routes):
        for a, b in alternatives:
            for host, router in (('client', a), ('server', b)):
                lines.append(f'        {host}[{i}].pppg++ <--> DatarateChannel {{ datarate = 10Gbps; delay = parent.pathRtt / 4; }} <--> router[{router}].pppg++;')
    return '\n'.join(lines + ['}', ''])


def general(number, protocol):
    # Reuse common transport/startup settings, not experiment 5's apps/topology.
    lines = common_general(5, protocol)
    lines = lines[:lines.index('*.client[*].numApps = 1')]
    lines = [l.replace('experiments.experiment5.fairnessPaths', f'experiments.experiment{number}.redistribution')
             .replace('sim-time-limit = 300s', f'sim-time-limit = {DURATION}s') for l in lines]
    lines += ['*.linkCapacity = 100Mbps', '*.pathRtt = 20ms',
              '**.tcp.subflowInterfaceBinding = true',
              '*.client[*].forwarding = false', '*.server[*].forwarding = false']
    routes = topology(number)[1]
    for i, alternatives in enumerate(routes):
        for host, app in (('client', 'MpTcpSessionApp'), ('server', 'MpTcpSinkApp')):
            scope = f'*.{host}[{i}]'
            lines += [f'{scope}.numApps = 1', f'{scope}.app[0].typename = "{app}"',
                      f'{scope}.app[0].numberOfSubflows = {len(alternatives)}',
                      f'{scope}.tcp.conn-*.numberOfSubflows = {len(alternatives)}']
        lines += [f'*.client[{i}].app[0].connectAddress = "server[{i}]"',
                  f'*.client[{i}].tcp.subflowRemoteAddresses = "' + ' '.join(f'server[{i}]>router[{b}]' for _, b in alternatives) + '"']
    lines += ['*.client[*].app[0].connectPort = 1000', '*.server[*].app[0].localPort = 1000',
              '*.client[*].app[0].tClose = -1s', '*.client[*].app[0].sendBytes = 1MiB',
              '*.client[*].app[0].dataTransferMode = "bytecount"',
              '*.server[*].app[0].serverThreadModuleType = "tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread"']
    queues = [f'*.{p}.queue' for p, _ in forward_interfaces(number)]
    lines += shuffle_settings(queues, protocol in SHUFFLE_PROTOCOLS)
    queue_type = 'MpOrbDeltaQueue' if protocol in SHUFFLE_PROTOCOLS else 'PintQueue'
    lines += [f'{q}.typename = "{queue_type}"' for q in queues]
    lines += ['**.ppp[*].queue.typename = "DropTailQueue"',
              '**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"',
              '# ceil(100e6 * .020 / (8 * 1448)): one propagation BDP.',
              '**.ppp[*].queue.packetCapacity = 173',
              '**.tcp.conn-temp.**.statistic-recording = false']
    for metric in METRICS:
        if metric in ('queueLength', 'pintLocalUtilization'):
            scopes = queues
        elif metric == 'transmissionState':
            # Exact path labels from source interface order; include all CCs.
            scopes = [f'*.{p}.ppp' for p, _ in forward_interfaces(number)]
            scopes += ['*.client[*].ppp[*].ppp']
        elif metric == 'goodput':
            scopes = ['*.server[*].app[0].**']
        else:
            host = 'server' if metric in ('throughput', 'holBlockedBytes') else 'client'
            scopes = [f'*.{host}[*].tcp.conn-*']
        mode = 'vector' if metric in ('goodput', 'throughput') else 'vector(removeRepeats)'
        for scope in scopes:
            lines += [f'{scope}.{metric}.statistic-recording = true',
                      f'{scope}.{metric}.result-recording-modes = {mode}',
                      f'{scope}.{metric}:{mode}.vector-recording = true']
    return lines + ['**.vector-recording = false', '**.scalar-recording = false', '**.bin-recording = false', '']


def generate(number, directory=None):
    directory = Path(directory) if directory else SIM_ROOT / f'experiments/experiment{number}'
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'redistribution.ned').write_text(network(number))
    for case in cases(number):
        scenario = ET.Element('scenario')
        for stop in sorted({end for _, _, end in waves(number, case)}):
            event = ET.SubElement(scenario, 'at', t=f'{stop}s')
            for i, _, end in waves(number, case):
                if end == stop:
                    ET.SubElement(event, 'set-param', module=f'client[{i}].tcp', par='sendingEnabled', value='false')
        ET.indent(scenario)
        ET.ElementTree(scenario).write(directory/f'{case.lower()}.xml', encoding='unicode')
    for protocol in PROTOCOLS:
        lines = general(number, protocol)
        for case in cases(number):
            for run in RUNS:
                config = f'{protocol}_{case}_Run{run}'
                starts = [random.Random(2999+run+i*100).uniform(.1, 2) for i in range(4)]
                starts += [DURATION+1]*(len(topology(number)[1])-4)
                for i, start, _ in waves(number, case): starts[i] = start
                lines += [f'[Config {config}]', f'seed-set = {run}',
                          f'*.scenarioManager.script = xmldoc("{case.lower()}.xml")',
                          f'output-vector-file = "results/{config}-#0.vec"',
                          f'output-scalar-file = "results/{config}-#0.sca"']
                for i, start in enumerate(starts):
                    lines += [f'*.client[{i}].app[0].tOpen = {start:.6f}s', f'*.client[{i}].app[0].tSend = {start:.6f}s']
                lines.append('')
        (directory/f'experiment{number}_{protocol.lower()}.ini').write_text('\n'.join(lines))
    print(f'Generated experiment {number}: {len(PROTOCOLS)} protocols × {len(cases(number))} cases × 5 runs; {DURATION}s.')
