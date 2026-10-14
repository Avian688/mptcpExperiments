"""Shared transport comparisons and explicit forward-bottleneck shuffle scope."""
PROTOCOLS = {'Alpha': ('MpOrb', 'MpOrbSemiCoupledAlpha', 'MpORB Alpha'),
 'Delta': ('MpOrb', 'MpOrbSemiCoupledDelta', 'MpORB Delta'),
 'Omega': ('MpOrb', 'MpOrbOmega', 'MpORB Omega'),
 'OrbUncoupled': ('MpOrb', 'MpOrbUncoupled', 'OrbCC uncoupled'),
 'CubicUncoupled': ('MpTcp', 'MpTcpMetaCubic', 'CUBIC uncoupled')}


def shuffle_settings(queues, delta):
    # OMNeT++ uses the first matching assignment: specific gates before fallback.
    lines = [f'{queue}.deltaShuffleFraction = 0.05' for queue in queues] if delta else []
    return lines + ['**.ppp[*].queue.deltaShuffleFraction = 0',
                    '**.ppp[*].queue.deltaShuffleInterval = 0s']

# Shared CC presentation order is the insertion order of PROTOCOLS above.
CC_LABELS = dict(zip(PROTOCOLS, ('Alpha', 'Delta', 'Omega', 'OrbCC uncoupled', 'CUBIC uncoupled')))
CC_COLORS = dict(zip(PROTOCOLS, ('#0072B2', '#CC79A7', '#E69F00', '#009E73', '#D55E00')))
