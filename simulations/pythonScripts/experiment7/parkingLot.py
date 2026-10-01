#!/usr/bin/env python3
"""Two-lane version of OrbTCP's three-rib parking-lot experiment."""
import math
from pathlib import Path
import random

SIM_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = SIM_ROOT / 'experiments/experiment7'
RTTS_MS = tuple(range(20, 201, 20))
RUNS = range(1, 6)
CAPACITY_MBPS = 100
MSS = 1448
INTERVAL = 1.0
PROTOCOLS = {
    'Alpha': ('MpOrb', 'MpOrbSemiCoupledAlpha', 'MpORB Alpha'),
    'Beta': ('MpOrb', 'MpOrbSemiCoupledBeta', 'MpORB Beta'),
    'CubicUncoupled': ('MpTcp', 'MpTcpMetaCubic', 'CUBIC uncoupled'),
    'OrbUncoupled': ('MpOrb', 'MpOrbUncoupled', 'OrbCC uncoupled'),
}
CONNECTIONS = ('Spine', 'Rib 1', 'Rib 2', 'Rib 3')
CLIENTS = ('spineClient', 'ribClient[0]', 'ribClient[1]', 'ribClient[2]')
SERVERS = ('spineServer', 'ribServer[0]', 'ribServer[1]', 'ribServer[2]')
QUEUES = tuple((f'lane{lane}Router[{link}].ppp[{0 if link == 0 else 1}].queue',
                f'Lane {lane + 1}, link {link + 1}')
               for lane in range(2) for link in range(3))
METRICS = ('goodput', 'throughput', 'cwnd', 'rtt', 'queueLength',
           'subflowSendQueueBytes', 'holBlockedBytes')


def duration(rtt_ms):
    return 2 * rtt_ms  # 2000 propagation RTTs, as in OrbTCP experiment 6.


def measurement_start(rtt_ms):
    return 1.5 * rtt_ms  # Final 500 RTTs; same window as its ratio plot.


def spine_start(rtt_ms, run):
    return random.Random(1998 + run).uniform(0, 0.5 * rtt_ms)


def packet_capacity(rtt_ms):
    return math.ceil(CAPACITY_MBPS * 1e6 * rtt_ms / 1000 / (8 * MSS))


def prefix(protocol, rtt_ms):
    return f'{protocol}_Rtt{rtt_ms}'


def slug(protocol, rtt_ms):
    return f'{protocol}/rtt{rtt_ms}ms'


def ini_name(protocol):
    return f'experiment7_{protocol.lower()}.ini'


def configurations():
    return [(prefix(p, rtt), slug(p, rtt), ini_name(p))
            for p in PROTOCOLS for rtt in RTTS_MS]


def general(protocol):
    tcp, algorithm, _ = PROTOCOLS[protocol]
    projects = ('mptcp', 'mporb', 'orbtcp', 'cubic', 'tcpPaced', 'tcpGoodputApplications')
    ned = ['../..', '../../../src']
    ned += [f'../../../../{p}/{d}' for p in projects for d in ('simulations', 'src')]
    ned += ['../../../../inet4.5/src']
    lines = [
        '[General]', 'ned-path = ' + ':'.join(ned),
        'network = mptcpexperiments.simulations.experiments.experiment7.twoLaneParkingLot',
        'record-eventlog = false', 'cmdenv-express-mode = true',
        'cmdenv-event-banners = false', '**.cmdenv-log-level = off',
        '*.configurator.config = xml("<config><interface hosts=\'**\' address=\'10.x.x.x\' netmask=\'255.x.x.x\'/><autoroute metric=\'delay\'/></config>")',
        '*.configurator.addDefaultRoutes = false', '*.configurator.addSubnetRoutes = false',
        '*.configurator.optimizeRoutes = false',
        f'*.linkCapacity = {CAPACITY_MBPS}Mbps',
        f'**.tcp.typename = "{tcp}"', f'**.tcp.tcpAlgorithmClass = "{algorithm}"',
        '**.schedulerMode = "defaultCwnd"', '**.startAllSubflowsAtBeginning = true',
        '**.subflowStartTimes = ""', '**.tcp.subflowInterfaceBinding = true',
        '**.tcp.advertisedWindow = 200000000', '**.tcp.windowScalingSupport = true',
        '**.tcp.windowScalingFactor = -1', '**.tcp.increasedIWEnabled = true',
        '**.tcp.delayedAcksEnabled = false', '**.tcp.timestampSupport = true',
        '**.tcp.ecnWillingness = false', '**.tcp.nagleEnabled = true',
        '**.tcp.sackSupport = true', '**.tcp.updatedSackEnabled = true',
        '**.tcp.stopOperationTimeout = 4000s', f'**.tcp.mss = {MSS}',
        '**.tcp.sendQueueLimit = 4MiB',
        '# Same fixed startup threshold as the OrbTCP parking-lot test.',
        f'**.tcp.initialSsthresh = {400 * MSS}',
        '**.additiveIncreasePercent = 0.05', '**.eta = 0.95', '**.alpha = 0.03',
        '**.fixedAvgRTTVal = 0s',
        '# Exact PINT controls, as in experiments 5/6; no quantisation/sampling error.',
        '**.pintBits = 0', '**.pintFlowCountBits = 0',
        '**.flowCountSketchEnabled = false', '**.pintFeedbackProbability = 1',
        '**.pintSeparateQueueingDelay = true',
        f'**.goodputInterval = {INTERVAL:g}s', f'**.throughputInterval = {INTERVAL:g}s',
    ]
    for client, server, exit_router in zip(CLIENTS, SERVERS, (3, 1, 2, 3)):
        for host, app in ((client, 'MpTcpSessionApp'), (server, 'MpTcpSinkApp')):
            lines += [f'*.{host}.numApps = 1', f'*.{host}.app[0].typename = "{app}"',
                      f'*.{host}.app[0].numberOfSubflows = 2',
                      f'*.{host}.tcp.conn-*.numberOfSubflows = 2']
        lines += [f'*.{client}.app[0].connectAddress = "{server}"',
                  f'*.{client}.tcp.subflowRemoteAddresses = "{server}>lane0Router[{exit_router}] {server}>lane1Router[{exit_router}]"',
                  f'*.{client}.app[0].connectPort = 1000',
                  f'*.{client}.app[0].tClose = -1s',
                  f'*.{client}.app[0].sendBytes = 1MiB',
                  f'*.{client}.app[0].dataTransferMode = "bytecount"',
                  f'*.{server}.app[0].localPort = 1000',
                  f'*.{server}.app[0].serverThreadModuleType = "tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread"']
    # Identical forward bottleneck queue implementation for all four algorithms.
    for queue, _ in QUEUES:
        lines.append(f'*.{queue}.typename = "PintQueue"')
    lines += ['**.ppp[*].queue.typename = "DropTailQueue"',
              '**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"',
              '**.tcp.conn-temp.**.statistic-recording = false']
    for metric in METRICS:
        if metric == 'queueLength':
            scopes = [f'*.{q}' for q, _ in QUEUES]
        elif metric == 'goodput':
            scopes = [f'*.{h}.app[0].**' for h in SERVERS]
        else:
            hosts = SERVERS if metric in ('throughput', 'holBlockedBytes') else CLIENTS
            scopes = [f'*.{h}.tcp.conn-*' for h in hosts]
        mode = 'vector' if metric in ('goodput', 'throughput') else 'vector(removeRepeats)'
        for scope in scopes:
            lines += [f'{scope}.{metric}.statistic-recording = true',
                      f'{scope}.{metric}.result-recording-modes = {mode}',
                      f'{scope}.{metric}:{mode}.vector-recording = true']
    # Specific recording rules above must precede this fallback. No blanket
    # statistic-recording=false: manually enabling another vector remains possible.
    lines += ['**.vector-recording = false', '**.scalar-recording = false',
              '**.bin-recording = false', '']
    return lines


def generate(number=7, directory=None):
    if number != 7:
        raise ValueError('This generator only handles experiment 7')
    directory = EXPERIMENT_DIR if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for protocol in PROTOCOLS:
        lines = general(protocol)
        for rtt in RTTS_MS:
            for run in RUNS:
                config = f'{prefix(protocol, rtt)}_Run{run}'
                lines += [f'[Config {config}]',
                          f'description = "{PROTOCOLS[protocol][2]}; two lanes; {rtt} ms; run {run}"',
                          f'seed-set = {run}', f'*.pathRtt = {rtt}ms',
                          f'sim-time-limit = {duration(rtt)}s',
                          f'output-vector-file = "results/{config}-#0.vec"',
                          f'output-scalar-file = "results/{config}-#0.sca"',
                          '# One BDP per bottleneck, rounded up at MSS 1448.',
                          f'**.ppp[*].queue.packetCapacity = {packet_capacity(rtt)}']
                for client in CLIENTS:
                    start = spine_start(rtt, run) if client == 'spineClient' else 0
                    lines += [f'*.{client}.app[0].tOpen = {start:.6f}s',
                              f'*.{client}.app[0].tSend = {start:.6f}s']
                lines.append('')
        (directory / ini_name(protocol)).write_text('\n'.join(lines))
    print('Generated experiment 7: 4 algorithms x 10 RTTs x 5 runs = 200 simulations.')
