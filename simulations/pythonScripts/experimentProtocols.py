"""Single source of truth for the five transport comparisons, in plot order."""
PROTOCOLS = {
    'Alpha': ('MpOrb', 'MpOrbSemiCoupledAlpha', 'Alpha'),
    'Delta': ('MpOrb', 'MpOrbDelta', 'Delta'),
    'Omega': ('MpOrb', 'MpOrbOmega', 'Omega'),
    'OrbUncoupled': ('MpOrb', 'MpOrbUncoupled', 'OrbCC uncoupled'),
    'CubicUncoupled': ('MpTcp', 'MpTcpMetaCubic', 'CUBIC uncoupled'),
}
SHUFFLE_PROTOCOLS = ('Delta', 'Omega')
SHUFFLE_CLASSES = tuple(PROTOCOLS[p][1] for p in SHUFFLE_PROTOCOLS)
CC_LABELS = {p: v[2] for p, v in PROTOCOLS.items()}
CC_COLORS = dict(zip(PROTOCOLS, ('#0072B2', '#882255', '#E69F00', '#009E73', '#D55E00')))


def legacy_protocols(short_alpha=False):
    """Keep existing filenames/config names for the older ABC runners."""
    keys = ('mporb_alpha' if short_alpha else 'mporb_semicoupled_alpha',
            'mporb_delta', 'mporb_omega', 'mporb', 'cubic')
    result = {}
    for key, (protocol, (tcp, algorithm, label)) in zip(keys, PROTOCOLS.items()):
        config = ('MpOrbAlpha' if short_alpha else algorithm) if protocol == 'Alpha' else (
            'CubicUncoupled' if protocol == 'CubicUncoupled' else algorithm)
        result[key] = dict(config=config, tcp_type=tcp, algorithm_class=algorithm, description=label)
    return result


def shuffle_settings(queues, enabled):
    if not enabled:
        return []
    return [f'{q}.deltaShuffleFraction = 0.05' for q in queues] + [
        '**.ppp[*].queue.deltaShuffleFraction = 0',
        '**.ppp[*].queue.deltaShuffleInterval = 0s']
