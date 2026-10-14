# Experiment 4: dynamic ABC

See the [suite guide](../README.md) for the current five-algorithm matrix and run command.

A uses paths 1–4; B uses 1,2,5,6; C uses 3,4,7,8. Five single-path background
connections per path join paths 5/6 at 30 s and stop admission at 60 s. A second
wave joins paths 1/2 at 90 s and stops admission at 120 s. All runs last 150 s.
All foreground/background connections use the selected algorithm: Alpha,
Delta, Omega, uncoupled OrbCC, or uncoupled CUBIC, with defaultCwnd.

The editable NED currently uses 100 Mbps core bottlenecks, 40 ms propagation RTT
and 10 Gbps access links. Generated buffers track the core BDP (346 packets at
MSS 1448). Only the eight forward core egress queues issue Delta shuffle; access
queues are disabled. The shuffle budget is 5% per average-RTT round.

The response plots show A/B/C goodput, background goodput by path, subflow
throughput and bottleneck queues. Heatmaps/phase summaries use the actual input
schedule. Old raw results are retained, but unselected algorithms are excluded.

Runner wall-clock timeout defaults to five hours (18,000 s), overridable with
`--sim-timeout-seconds` or `EXPERIMENT_SIM_TIMEOUT_SECONDS`. Simulation durations
are unchanged. Allocation comparisons use separate connection panels and consistent
algorithm colours; means and sample SD are computed across repetitions.
