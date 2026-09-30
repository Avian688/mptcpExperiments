#!/usr/bin/env python3
"""Definitions and INI generation for the small MpORB validation experiments.

Experiment 1 combines busy-path redistribution and the inter-RTT sweep.
Experiments 5 and 6 isolate allocation and dependence on arrival order.
"""
from pathlib import Path
import random
import re
import xml.etree.ElementTree as ET

SIM_ROOT = Path(__file__).resolve().parents[1]
RUNS = range(1, 6)
# Same range as orbtcpExperiments/pythonScripts/experiment5's inter-RTT test.
RTTS_MS = tuple(range(20, 201, 20))
MSS = 1448
METRICS = (
    'goodput', 'throughput', 'cwnd', 'srtt', 'mbytesInFlight',
    'subflowSendQueueBytes', 'holBlockedBytes', 'U', 'sharingFlows',
    'bottleneckBandwidth', 'semiCoupledAlphaSubflowRate',
    'semiCoupledAlphaConnectionRate', 'semiCoupledAlphaRateShare',
    'queueLength', 'bandwidth', 'numberOfFlows', 'pintLocalUtilization',
    'cwndLimited', 'retransmissionRate',
)
BETA_METRICS = (
    'mpOrbBetaWeight', 'mpOrbBetaWeightCorrection', 'mpOrbBetaSmoothedU',
    'mpOrbBetaUtilizationError', 'mpOrbBetaRateShare', 'mpOrbBetaBaselineShare',
    'mpOrbBetaRedistributionActive', 'mpOrbBetaAlphaAi',
    'mpOrbBetaUncoupledAi', 'mpOrbBetaWeightedAi',
)
NETWORKS = {1: 'busyPaths', 5: 'fairnessPaths', 6: 'sharedleopaths'}
DURATIONS = {1: 240, 5: 300, 6: 300}
USER_PATHS = {
    1: ((1, 2), (1,), (2,)),
    5: ((1, 2), (1,), (1,)),
    6: ((1, 2, 3, 4), (1, 2, 5, 6), (3, 4, 7, 8)),
}


def protocols(number):
    return ('Alpha', 'Beta') if number in (5, 6) else ('Alpha',)


def cases(number, protocol=None):
    if protocol is None:
        return [case for name in protocols(number) for case in cases(number, name)]
    if protocol not in protocols(number):
        raise ValueError(f'Unsupported protocol for experiment {number}: {protocol}')
    if number == 1:
        return [(f'Alpha_Rtt20_{rtt}', f'rtt20_{rtt}', f'RTT (20, {rtt}) ms')
                for rtt in RTTS_MS]
    if number == 5:
        scenarios = [('Fairness', 'fairness', 'Two shared links and a private route')]
    elif number == 6:
        scenarios = [(order, order, title) for order, title in (
            ('Together', 'A, B, C start together'),
            ('AFirst', 'A starts before B and C'),
            ('BCFirst', 'B and C start before A'))]
    else:
        raise ValueError(f'Unsupported MpORB experiment: {number}')
    # Preserve existing Alpha paths; Beta outputs must never overwrite them.
    return [(f'{protocol}_{name}', slug if protocol == 'Alpha' else f'beta_{slug}', title)
            for name, slug, title in scenarios]


def phases(number):
    if number == 1:
        return [(5, 60, 'Baseline'), (60, 120, 'Competition'), (120, 240, 'Recovery')]
    if number == 6:
        return [(65, 300, 'All connections active')]
    return [(5, 300, 'Steady topology')]


def reference(number, phase, objective='maxmin'):
    """Ideal full-capacity rates in Mbps, not predictions of Alpha goodput."""
    if number == 1:
        return (50., 50., 20.) if phase == 'Competition' else (200/3,) * 3
    if number == 5:
        return (60., 60., 60.) if objective == 'maxmin' else (40., 80., 80.)
    # Experiment 6 inherits the editable ABC topology; do not assume 100 Mbps.
    source = (SIM_ROOT / 'experiments/experiment6/sharedleopaths.ned').read_text()
    link = re.search(r'channel bottleneckPath.*?datarate\s*=\s*([\d.]+)Mbps', source, re.S)
    if link is None:
        raise ValueError('Cannot read experiment 6 bottleneck capacity in Mbps')
    return (8 * float(link[1]) / 3,) * 3


def general(number, protocol='Alpha'):
    projects = ('mptcp', 'mporb', 'orbtcp', 'cubic', 'tcpPaced', 'tcpGoodputApplications')
    ned = ['../..', '../../../src']
    ned += [f'../../../../{p}/{d}' for p in projects for d in ('simulations', 'src')]
    ned += ['../../../../inet4.5/src']
    lines = [
        '[General]', 'ned-path = ' + ':'.join(ned),
        f'network = mptcpexperiments.simulations.experiments.experiment{number}.{NETWORKS[number]}',
        f'sim-time-limit = {DURATIONS[number]}s', 'record-eventlog = false',
        'cmdenv-express-mode = true', 'cmdenv-event-banners = false',
        '**.cmdenv-log-level = off',
        '*.configurator.config = xml("<config><interface hosts=\'**\' address=\'10.x.x.x\' netmask=\'255.x.x.x\'/><autoroute metric=\'delay\'/></config>")',
        '*.configurator.addDefaultRoutes = false', '*.configurator.addSubnetRoutes = false',
        '*.configurator.optimizeRoutes = false',
        '**.tcp.typename = "MpOrb"', f'**.tcp.tcpAlgorithmClass = "MpOrbSemiCoupled{protocol}"',
        '**.schedulerMode = "defaultCwnd"', '**.startAllSubflowsAtBeginning = true',
        '**.subflowStartTimes = ""', '**.tcp.advertisedWindow = 200000000',
        '**.tcp.windowScalingSupport = true', '**.tcp.windowScalingFactor = -1',
        '**.tcp.increasedIWEnabled = true', '**.tcp.delayedAcksEnabled = false',
        '**.tcp.timestampSupport = true', '**.tcp.ecnWillingness = false',
        '**.tcp.nagleEnabled = true', '**.tcp.sackSupport = true',
        '**.tcp.updatedSackEnabled = true', '**.tcp.stopOperationTimeout = 4000s',
        f'**.tcp.mss = {MSS}', '**.tcp.sendQueueLimit = 4MiB',
        '# Fixed startup threshold: half of the 100 Mbps / 20 ms reference BDP.',
        f'**.tcp.initialSsthresh = {86 * MSS}',
        '**.additiveIncreasePercent = 0.05', '**.eta = 0.95', '**.alpha = 0.03',
        '**.fixedAvgRTTVal = 0s',
        '# Exact PINT values/counts, full ACK feedback; estimator dynamics remain enabled.',
        '**.pintBits = 0', '**.pintFlowCountBits = 0',
        '**.flowCountSketchEnabled = false', '**.pintFeedbackProbability = 1',
        '**.pintSeparateQueueingDelay = true',
        '**.goodputInterval = 0.5s', '**.throughputInterval = 0.5s',
    ]
    for host, app in (('client', 'MpTcpSessionApp'), ('server', 'MpTcpSinkApp')):
        lines += [f'*.{host}[*].numApps = 1', f'*.{host}[*].app[0].typename = "{app}"']
    lines += [
        '*.client[*].app[0].tClose = -1s', '*.client[*].app[0].sendBytes = 1MiB',
        '*.client[*].app[0].dataTransferMode = "bytecount"',
        '*.client[*].app[0].connectPort = 1000', '*.server[*].app[0].localPort = 1000',
        '*.server[*].app[0].serverThreadModuleType = "tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread"',
    ]
    routes = {
        1: ('p1Egress p2Egress', 'p1Egress', 'p2Egress'),
        5: ('right privateEgress', 'middle', 'right'),
        6: ('router2[0] router2[1] router2[2] router2[3]',
            'router2[0] router2[1] router2[4] router2[5]',
            'router2[2] router2[3] router2[6] router2[7]'),
    }[number]
    if number == 1:
        routes += ('p2Egress',) * 4
        lines += ['*.path1Rtt = 20ms', '*.scenarioManager.script = xmldoc("conditions.xml")']
    for i, route in enumerate(routes):
        count = len(route.split())
        for host in ('client', 'server'):
            lines += [f'*.{host}[{i}].app[0].numberOfSubflows = {count}',
                      f'*.{host}[{i}].tcp.conn-*.numberOfSubflows = {count}']
        lines += [f'*.client[{i}].app[0].connectAddress = "server[{i}]"',
                  f'*.client[{i}].tcp.subflowRemoteAddresses = "' +
                  ' '.join(f'server[{i}]>{r}' for r in route.split()) + '"']
    if number == 1:
        queues = ['p1Ingress.ppp[0]', 'p2Ingress.ppp[0]']
    elif number == 5:
        queues = ['left.ppp[0]', 'middle.ppp[1]', 'privateIngress.ppp[0]']
        lines += ['*.privateIngress.ppp[0].queue.packetCapacity = 35']
    else:
        queues = [f'router1[{i}].ppp[{2 if i < 4 else 1}]' for i in range(8)]
    for queue in queues:
        lines += [f'*.{queue}.queue.typename = "PintQueue"']
    lines += [
        '**.ppp[*].queue.typename = "DropTailQueue"',
        '**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"',
        '# Fixed ceil(100 Mbps * 20 ms / (8 * 1448 B)) = 173 packets.',
        '# Keep this fixed across the RTT sweep; the private 20 Mbps link uses 35.',
        '**.ppp[*].queue.packetCapacity = 173',
        '**.tcp.conn-temp.**.statistic-recording = false',
    ]
    for metric in METRICS + (BETA_METRICS if protocol == 'Beta' else ()):
        if metric in ('queueLength', 'bandwidth', 'numberOfFlows', 'pintLocalUtilization'):
            scopes = [f'*.{queue}.queue' for queue in queues]
        elif metric == 'goodput':
            scopes = ['*.server[*].**']
        else:
            host = 'server' if metric in ('throughput', 'holBlockedBytes') else 'client'
            scopes = [f'*.{host}[{i}].tcp.conn-*' for i in range(3)]
        for scope in scopes:
            lines += [f'{scope}.{metric}.statistic-recording = true',
                      f'{scope}.{metric}.result-recording-modes = vector',
                      f'{scope}.{metric}:vector.vector-recording = true']
    # No blanket statistic-recording=false: changing a vector rule must work.
    # Rate vectors are uncompressed so a quiet interval cannot masquerade as load.
    lines += ['**.vector-recording = false', '**.scalar-recording = false',
              '**.bin-recording = false', '']
    return lines


def generate(number):
    directory = SIM_ROOT / 'experiments' / f'experiment{number}'
    directory.mkdir(parents=True, exist_ok=True)
    for protocol in protocols(number):
        generate_protocol(number, protocol, directory)
    if number == 1:
        scenario = ET.Element('scenario')
        event = ET.SubElement(scenario, 'at', t='120s')
        for i in range(3, 7):
            ET.SubElement(event, 'set-param', module=f'client[{i}].tcp',
                          par='sendingEnabled', value='false')
        ET.indent(scenario)
        ET.ElementTree(scenario).write(directory / 'conditions.xml', encoding='unicode')
    if number == 6:
        source = (SIM_ROOT / 'experiments/experiment2/sharedleopaths.ned').read_text()
        source = source.replace('experiments.experiment2', 'experiments.experiment6')
        source = source.replace('access40ms', 'access20ms').replace('delay = 10ms;', 'delay = 5ms;')
        (directory / 'sharedleopaths.ned').write_text(source)
    print(f'Generated experiment {number}: {len(cases(number)) * len(RUNS)} configurations.')


def generate_protocol(number, protocol, directory):
    lines = general(number, protocol)
    for prefix, slug, title in cases(number, protocol):
        for run in RUNS:
            rng = random.Random(2999 + run)
            starts = [rng.uniform(0.1, 5) for _ in range(3)]
            if number == 1:
                starts += [60.] * 4
            elif number == 6:
                # Same start offsets per run in all orders; late group joins at 60 s.
                order = prefix.split('_', 1)[1]
                late = {'AFirst': (1, 2), 'BCFirst': (0,), 'Together': ()}[order]
                if order == 'Together':
                    starts = [starts[0]] * 3
                else:
                    for i in late:
                        starts[i] += 60
            config = f'{prefix}_Run{run}'
            lines += [f'[Config {config}]', f'description = "{protocol}; {title}; run {run}"',
                      f'seed-set = {run}',
                      f'output-vector-file = "results/{config}-#0.vec"',
                      f'output-scalar-file = "results/{config}-#0.sca"']
            if number == 1:
                lines += [f'*.path2Rtt = {slug.split("_")[-1]}ms']
            for i, start in enumerate(starts):
                lines += [f'*.client[{i}].app[0].tOpen = {start:.6f}s',
                          f'*.client[{i}].app[0].tSend = {start:.6f}s']
            lines.append('')
    (directory / f'experiment{number}_mporb_{protocol.lower()}.ini').write_text('\n'.join(lines))
