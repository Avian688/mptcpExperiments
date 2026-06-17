# MPTCP Experiment Diagrams

Generated meeting diagrams for the two `mptcpExperiments` setups.

## Experiment 1

- One user, two subflows.
- Path 0: fixed 20 ms RTT, 10 Mbps bottleneck.
- Path 1: swept 20-180 ms RTT, 100 Mbps bottleneck.
- Queue size: 1554 packets, based on the highest swept BDP.
- Compare CUBIC and MPORB across default, lowestRTT, and directPull schedulers.
- Metrics: aggregate goodput, per-subflow goodput, HoL blocked bytes, DSN gap.

## Experiment 2

- Three users, four subflows each.
- Eight LEO-like paths, all 100 Mbps, RTTs 60-130 ms.
- Queue size: 1123 packets, based on the highest path BDP.
- User A uses paths 1-4; B uses 1,2,5,6; C uses 3,4,7,8.
- Expected uncoupled failure: A gets less aggregate goodput because all of A's paths are shared.
