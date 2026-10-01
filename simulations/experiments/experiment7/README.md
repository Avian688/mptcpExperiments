# Experiment 7: two-lane parking lot

Two independent copies of the three-link parking lot in
`orbtcpExperiments/simulations/paperExperiments/experiment6/parkinglot.ned`.
There are four **connections**, each with exactly **two subflows**:

| Connection | Subflow in lane 1 | Subflow in lane 2 |
| --- | --- | --- |
| Spine | Links 1, 2, 3 | Links 1, 2, 3 |
| Rib 1 | Link 1 | Link 1 |
| Rib 2 | Link 2 | Link 2 |
| Rib 3 | Link 3 | Link 3 |

Every core link is 100 Mbps. Each subflow has two 10 Gbps access legs;
propagation delay is placed on these legs so crossing three core links does
not itself give the spine a longer propagation RTT. The two lanes have
separate routers and links, with no cross-lane links. Hosts bind subflow 0 to
ppp0/lane 1 and subflow 1 to ppp1/lane 2, with explicit remote interface addresses.

## Matrix and timing

- MpORB Alpha, MpORB Beta, uncoupled CUBIC (`MpTcpMetaCubic`), and uncoupled
  OrbCC/PINT (`MpOrbUncoupled`). All connections in a run use the selected CC.
- `defaultCwnd` for every connection and algorithm.
- RTTs **20, 40, ..., 200 ms**, applied equally to both lanes and all connections
  in each case, matching the source parking-lot sweep. Baseline: 20/20 ms.
- Five paired seeds per case: **200 simulations** in total.
- One BDP of buffering per bottleneck: `ceil(100e6 * RTT / (8 * 1448))`
  packets, from 173 at 20 ms to 1727 at 200 ms. Each lane gets its own buffer.
- As in the source experiment, ribs start at 0, the spine starts at a seeded
  time in the first 500 RTTs, duration is 2000 RTTs (40–400 s), and summaries
  use the final 500 RTTs (last quarter). Starts are identical across algorithms.
- Sender queues continuously refill after the initial application write;
  `sendBytes=1MiB` seeds transmission and `tClose=-1s` keeps connections open.
- Fixed links: the source experiment's periodic hard handovers are intentionally
  omitted to isolate parking-lot allocation. No background admission events.
- Exact PINT controls match experiments 5/6: no U/count quantisation, no flow
  sketch, full feedback. Queue estimator dynamics and feedback delay remain.
  The same forward PintQueue instances and capacities are used for CUBIC;
  CUBIC does not use the INT feedback for congestion control.

## What it measures

The spine encounters three distinct congested links per subflow. Each rib
encounters only one. This tests whether multiple bottlenecks penalise a long
connection, even though the two paths within each connection are edge-disjoint.

For ideal full-capacity connection rates, each rib obeys `Spine + Rib_i <= 200`.
Connection max–min therefore gives **100 Mbps each**. Connection proportional
fairness gives **50 Mbps to the spine and 150 Mbps to each rib**. These are
reference allocations, not predictions of Alpha/Beta, and ignore protocol
overhead and OrbCC headroom. Aggregate application goodput can differ between
allocations because a spine byte consumes three core links.

The principal plot matches the source experiment: at each sampled time, compare
spine goodput with the largest rib goodput using `min / max`, then average over
the final quarter. It equals 1 at ideal max–min and 1/3 at ideal proportional
fairness. The CSV also retains the directional `Spine / max(Ribs)` ratio, since
the bounded ratio alone cannot distinguish a spine advantage from disadvantage.

## Running

From the OMNeT++ checkout root, run the full pipeline with ten workers:

```sh
python3 samples/mptcpExperiments/simulations/pythonScripts/experiment7/runExperiment7.py --cores 10 --resume --skip-generate
```

To run just the four algorithms at 20/20 ms, retain five runs and add:

```sh
--configs Alpha_Rtt20 Beta_Rtt20 CubicUncoupled_Rtt20 OrbUncoupled_Rtt20
```

The runner generates configurations unless `--skip-generate` is supplied. It
reuses the experiment 5/6 pipeline for parallel simulations, export, extraction,
and plotting, with barriers between stages. `--resume` requires successful
completion markers matching inputs/libraries; a teardown crash is not completed.
`--dry-run --skip-generate` lists commands without running OMNeT++.
`--runs 1` is a single-repetition diagnostic. Defaults: five runs, three retries.

Replot extracted CSVs:

```sh
python3 samples/mptcpExperiments/simulations/pythonScripts/experiment7/plotExperiment7.py
```

## Plots and recording

Outputs go directly under `simulations/plots/experiment7`, with algorithm,
RTT and run subdirectories. No bars, and no repetition-count labels on figures.

- `goodput_ratio`: four-algorithm comparison versus RTT, mean ± sample SD of
  the **per-run** ratios; ideal max–min and proportional references.
- `goodput_by_rtt`: connection goodput versus RTT, with separate spine/rib panels.
- Per case: `goodput_mean_variance`, mean ± SD and a sample-variance panel.
- Per run: `goodput`, `throughput`, `cwnd`, `rtt`, `queueLength`, and `transport`
  (unsent subflow send queues and receiver HoL). Cwnd/RTT/queue plots retain
  recorded event times. Subflows are labelled by local connection ID; these IDs
  are not assumed to identify the same lane at both endpoints.
- All figures are PNG and PDF. CSVs: `run_summary.csv`, `summary.csv`,
  `goodput_time_statistics.csv`, and `coverage.csv`.

Only vectors used in these plots are enabled. Periodic goodput/throughput rates
are uncompressed; state vectors remove repeated values. Missing rate intervals
remain unknown. Summaries require at least 95% common final-window coverage
across the four connections, excluding the final potentially unrecorded one-second
timer interval from this check. The CSV reports coverage of the entire window;
unrecorded tails are never extrapolated. SD is undefined for one run, rather than zero.

Validation covers generated inputs, NED parsing/topology structure, dry-run
commands, extraction, and synthetic plots. No simulation performance is claimed.
