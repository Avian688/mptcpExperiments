"""Shared transport comparisons and explicit forward-bottleneck shuffle scope."""
PROTOCOLS = {
    'Alpha': ('MpOrb', 'MpOrbSemiCoupledAlpha', 'MpORB Alpha'),
    'OrbUncoupled': ('MpOrb', 'MpOrbUncoupled', 'OrbCC uncoupled'),
    'CubicUncoupled': ('MpTcp', 'MpTcpMetaCubic', 'CUBIC uncoupled'),
    'Delta': ('MpOrb', 'MpOrbSemiCoupledDelta', 'MpORB Delta'),
}


def shuffle_settings(queues, delta):
    # OMNeT++ uses the first matching assignment: specific gates before fallback.
    lines = [f'{queue}.deltaShuffleFraction = 0.05' for queue in queues] if delta else []
    return lines + ['**.ppp[*].queue.deltaShuffleFraction = 0',
                    '**.ppp[*].queue.deltaShuffleInterval = 0s']
