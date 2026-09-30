# MPTCP Experiment Diagrams

Generated meeting diagrams for the two `mptcpExperiments` setups.

## Experiment 2

- Three users, four subflows each.
- Eight LEO-like paths, all 100 Mbps, RTTs 60-130 ms.
- Queue size: 1123 packets, based on the highest path BDP.
- User A uses paths 1-4; B uses 1,2,5,6; C uses 3,4,7,8.
- Expected uncoupled failure: A gets less aggregate goodput because all of A's paths are shared.
