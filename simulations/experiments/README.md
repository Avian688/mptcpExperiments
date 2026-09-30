# MPTCP / MpORB experiments

The numbered suite was reorganised on 2026-09-29. The former experiments 1
(scheduler negatives) and 3 (OLIA Pareto topology) were removed.

| Number | Setup | Previous number |
| --- | --- | --- |
| 1 | Alpha redistribution on two busy paths, including the inter-RTT sweep | New |
| 2 | Static A/B/C topology with eight paths | 2, unchanged |
| 3 | Two-path responsiveness with five temporary competitors | 4 |
| 4 | A/B/C topology with two waves of background connections | 5 |
| 5 | Alpha/Beta fairness: two shared links in series and a private route | New |
| 6 | Alpha/Beta start-order dependence on the A/B/C topology | New |

The separately named scheduler and K-shortest-path experiments retain their names.
Existing results for retained experiments move with their experiment directories.
The old experiments' results and scripts were removed at the user's request.

## MpORB validation tests

Experiment 1 uses `MpOrbSemiCoupledAlpha`. Experiments 5 and 6 run both
`MpOrbSemiCoupledAlpha` and `MpOrbSemiCoupledBeta` by default, with five paired
seeds per case and identical topology, scheduler and start times. All participants
within each case use its selected algorithm, including one-subflow connections. The scheduler is fixed to `defaultCwnd`; this is not a
scheduler comparison. Change it in `pythonScripts/alphaValidation.py` and regenerate
if a different fixed scheduler is desired. Existing experiments' scheduler and CC
settings were retained.

There are five seeded runs per case. Initial starts use reproducible offsets in
0.1–5 s, paired between cases. Sender queues refill after application data starts;
`sendBytes = 1MiB` seeds that existing transport behaviour and `tClose = -1s`
keeps long-lived connections open. Stopping a temporary connection disables new
meta-level admission through `sendingEnabled`; already admitted data can drain.
Plots mark the scheduled admission changes, not an assumption of instant silence.

The new tests use exact PINT U encoding (`pintBits = 0`), exact flow sets
(`flowCountSketchEnabled = false`), unencoded counts (`pintFlowCountBits = 0`),
and full feedback (`pintFeedbackProbability = 1`). This removes telemetry
compression/sampling error, not estimator averaging, flow-count epochs, RTT or
ACK delay. These are **exact PINT control experiments**, not Full-INT.

All new tests use a 20 ms baseline propagation RTT and 10 Gbps access links.
Experiments 1 and 5 use 100 Mbps shared bottlenecks; experiment 6 uses its
current editable NED capacity (20 Mbps). Queues have 173 packets: the ceiling of a 100 Mbps,
20 ms BDP divided by MSS 1448 bytes. This packet budget stays fixed throughout
the RTT sweep. Experiment 5's private 20 Mbps link has 35 packets. Queue sizing
uses payload MSS, consistently with the existing experiments.

### Experiment 1: busy-path redistribution and inter-RTT

A has two edge-disjoint paths; B uses path 1 only; C uses path 2 only. Four
additional one-subflow connections join path 2 at 60 s and stop admitting data
at 120 s. Simulation duration is 240 s.

Path 1 propagation RTT is always 20 ms. Path 2 takes **20, 40, 60, 80, 100,
120, 140, 160, 180, 200 ms**, matching
`orbtcpExperiments/simulations/pythonScripts/experiment5/generateExperiment5Scenarios.py`.
All connections traversing a path have that path's RTT; the sweep does not add
OrbTCP's handover events. There are 50 runs, including five 20/20 ms baselines.

| Phase | Ideal A | Ideal B | Ideal C | Each added connection |
| --- | ---: | ---: | ---: | ---: |
| Before 60 s | 66.67 | 66.67 | 66.67 | Inactive |
| 60–120 s | 50 | 50 | 20 | 20 |
| After 120 s | 66.67 | 66.67 | 66.67 | Draining/inactive |

Rates are Mbps. Both ideal connection max–min and proportional fairness give
these values. A's corresponding path rates are (33.33, 33.33), (50, 0), and
(33.33, 33.33). A practical positive floor/probe rate need not be literally zero.
C remains backlogged after the additions stop: recovery cannot depend on lasting
underutilisation of path 2.

### Experiment 5: distinguish allocation objectives

A's first route crosses two 100 Mbps links in series; its second route uses a
private 20 Mbps link. B uses only the first shared link and C only the second.
A's routes are edge-disjoint. All route propagation RTTs are 20 ms. Run 300 s.

If A's shared-route rate is z and its private route is full, connection totals
are (20+z, 100-z, 100-z) Mbps. Ideal max–min gives (60,60,60); ideal proportional
fairness gives (40,80,80). The plots show both references; neither is presented
as a proven property of either algorithm. Five runs each: ten total.

### Experiment 6: start-order dependence

Reuse experiment 2's paths: A=(1,2,3,4), B=(1,2,5,6), C=(3,4,7,8), with
all eight paths currently at 20 Mbps / 20 ms in the editable NED topology. The existing experiment 2
remains at its original RTT. Run 300 s, with three arrival orders:

- Together: A/B/C start at the same seeded time in 0.1–5 s.
- AFirst: A starts in 0.1–5 s; B/C join in 60.1–65 s.
- BCFirst: B/C start in 0.1–5 s; A joins in 60.1–65 s.

Five runs per order and algorithm, 30 total. Final connection rates should be independent of
arrival order if the same intended equilibrium is reached. The ideal equal
allocation is eight times the configured path capacity divided by three
(53.33 Mbps at the current 20 Mbps). Plots read this capacity from the NED. Subflow splits may differ without
changing connection fairness or link utilisation.

## Running and plotting

Experiments **4, 5 and 6 default to Alpha and Beta**. The other experiment 4
algorithms remain available through `--configs`. From the OMNeT++ checkout root,
run the checked-in, paired configurations with ten workers (50 simulations):

```sh
for n in 4 5 6; do python3 samples/mptcpExperiments/simulations/pythonScripts/experiment${n}/runExperiment${n}.py --cores 10 --resume --skip-generate || break; done
```

`--skip-generate` uses the checked-in INIs. Experiment 4's Alpha/Beta INIs and
scenario have been restored to the generated baseline: 150 s duration,
30–60/90–120 s background schedule, `defaultCwnd` scheduler and selected vector
recording. Beta matches Alpha's setup. Link capacities remain specified in NED.
Experiments 5/6 generate both algorithms when regeneration is requested.
Their Alpha results keep existing paths; Beta uses separate `beta_...` case
folders. Comparison plots distinguish the algorithms and never pool their runs.


From `samples/mptcpExperiments`, run all **new** cases with ten workers:

```sh
for n in 1 5 6; do
    python3 simulations/pythonScripts/experiment$n/runExperiment$n.py --cores 10 --resume || break
done
```

The pipeline generates configs, simulates, exports CSV-R, extracts selected
metrics, and plots. Workers apply to simulation, export and extraction, with
barriers between stages. Defaults are five runs and three retries of failed jobs.
`--resume` skips only successful runs with matching configuration/topology/library
fingerprints and nonempty vector/scalar files. A teardown crash is not marked
complete. Output vectors retain the exact `-#0.vec` suffix.

To run only the baseline, or replot existing extracted data:

```sh
python3 simulations/pythonScripts/experiment1/runExperiment1.py --cores 10 --configs Alpha_Rtt20_20 --resume
python3 simulations/pythonScripts/experiment1/plotExperiment1.py
```

Use the equivalent numbered scripts for 5 and 6. `--start-step 2` exports existing
vectors, `--start-step 3` re-extracts exported CSV, and `--start-step 4` only plots.
`--runs 1` on a runner is a one-run diagnostic; the default remains five.

## Outputs and interpretation

Each case/run produces response, sender telemetry, and bottleneck diagnostic
plots. Each case also has mean goodput ± one sample standard deviation and a
separate sample-variance panel, in Mbps². The top-level allocation comparison
uses points/lines with SD, not bars. Missing samples and missing runs remain
unknown; coverage is written separately rather than added to plot annotations.

CSV outputs include `phase_runs.csv`, `phase_summary.csv`,
`goodput_time_statistics.csv`, and `coverage.csv`. Summaries report final-20-second
rates, delivered MB per phase, and time until all A/B/C goodputs stay within 5%
of the **ideal max–min reference** for five seconds. Non-convergence is NaN, not
zero. These are nominal full-capacity reference lines: protocol overhead,
OrbCC headroom and transient drain time are not removed. Failure to hit such a
reference must not be confused with failure to settle to Alpha's own equilibrium.

Only selected diagnostic vectors are recorded. Broad vector/scalar recording
stays off, with no blanket `statistic-recording=false` that would prevent enabling
an extra vector. Rate samples are uncompressed to preserve silent intervals.

Validation of this reorganisation covers NED syntax, configuration generation,
runner commands and synthetic plotting. No new simulation results are claimed.
