# Experiment 5: shared paths with temporary MPORB competition

Clones experiment 2's A/B/C topology and foreground protocol settings. Uses
experiment 4's mutable `sendingEnabled` control to stop background admission.
Experiments 2 and 4 are not modified by this experiment.

| Time | Background traffic |
| --- | --- |
| 0–30 s | None; A/B/C start at the same seeded times in 0–5 s as experiment 2 |
| 30–60 s | Five one-subflow MPORB connections on path 5 and five on path 6 |
| 60–90 s | Background admission disabled; A/B/C continue |
| 90–120 s | Five new one-subflow MPORB connections on path 1 and five on path 2 |
| 120–150 s | Background admission disabled; A/B/C continue |

A uses paths 1,2,3,4; B uses 1,2,5,6; C uses 3,4,7,8. Each path is
30 Mbps with approximately 40 ms propagation RTT, two 10 Gbps access legs,
and 104-packet queues (one BDP at MSS 1448). Added access links follow the
original bottlenecks in NED so the bottleneck PPP indices stay unchanged.
Each background host has a single physical attachment to its assigned path.
Hosts 0–4 use path 5, 5–9 path 6, 10–14 path 1, and 15–19 path 2.

Backgrounds always use `MpOrb` / `MpOrbUncoupled` with one subflow, even when
A/B/C use LIA, OLIA, or BALIA. Their initial slow-start threshold is 40,000 bytes,
as in experiment 4. All forward bottlenecks use PintQueue so background MPORB
receives PINT in every comparison. Other queue types, sizes and foreground
parameters follow experiment 2. PINT defaults include 8-bit encoding and flow
count sketching.

At 60/120 s the scenario stops **new data admission** at the background sender.
Already admitted packets and retransmissions may drain afterward; connections
are not destroyed and packets are not erased from shared queues. Background
sink goodput is plotted through 150 s to expose the drain. Start times trigger
connection establishment, so useful data begins after the handshake.

All sources use a 1 MiB application write to initiate transport's existing
continuous queue refill, rather than adding a second 2 GB backlog. Application
close is at 151 s, beyond the 150 s horizon. The first phase allows settling;
its duration alone is not evidence that equilibrium was reached.

## Run

From the OMNeT++ checkout root, with the usual built project libraries and a
Python environment containing NumPy, pandas and Matplotlib:

```sh
# Same nine default protocols as experiment 2, five seeds each: 45 simulations.
python3 samples/mptcpExperiments/simulations/pythonScripts/experiment5/runExperiment5.py --cores 10 --resume

# Alpha only: five simulations.
python3 samples/mptcpExperiments/simulations/pythonScripts/experiment5/runExperiment5.py --configs MpOrbSemiCoupledAlpha --cores 5 --resume

# Inspect one command without launching a simulation.
python3 samples/mptcpExperiments/simulations/pythonScripts/experiment5/runExperiment5.py --configs MpOrbSemiCoupledAlpha --runs 1 --dry-run
```

Generated INIs also include optional `CubicUncoupled`, selectable with `--configs`.
The generator reuses experiment 2's settings code, so keep both script folders.
`--runs N` selects seeds 1 through N (maximum five). Steps are 1=simulate,
2=export, 3=extract, 4=plot; `--end-step 1` runs simulations only. Use
`--start-step 2` for subsequent export and plotting. `--retries 0` disables
retries (the cloned runner defaults to three retries).

`--resume` skips only clean successful runs with valid completion markers and
matching commands, INI/topology/scenario inputs, library metadata and output
metadata. A teardown abort is a failure. Rebuilding libraries invalidates these
markers. `--dry-run` regenerates inputs but neither builds nor simulates.

Plots and phase summaries require the complete 150 s experiment. If using
`--sim-time-limit` for a short diagnostic, stop at step 3 and run the full
experiment before plotting.

## Results

Raw results and completion markers are in this directory's `results/`;
extracted metrics are in `csvs/<protocol>/runN/`. Logs are in
`simulations/logs/experiment5/`; plots are in `simulations/plots/experiment5/`.

Each run has a PNG/PDF response plot with A/B/C application goodput, background
goodput grouped by path, per-subflow received throughput for A/B/C, and all eight
bottleneck queues. Shading marks both load episodes. Subflow throughput includes
retransmissions and is not application goodput. Subflow-to-path ordering follows
experiment 2's connection-creation convention.

`phase_goodput.png` and `.pdf` compare A/B/C goodput for the final ten seconds
of each phase, annotated with mean, sample SD and run count. `phase_runs.csv`
and `phase_summary.csv` contain both whole-phase and final-ten-second summaries,
including background goodput, subflow throughput and queue occupancy. These are
measurement windows, not an assertion that convergence has occurred. No static
80 Mbps fairness target is imposed during competition.

Rates use the preceding 0.5-second measurement interval and a 0.5-second analysis
grid; the first partial interval after connection establishment is approximate.
Missing runs are omitted and run counts are explicit. Missing background
measurements produce unknown values rather than invented zero traffic.

Validation: generated inputs, NED syntax, dry-run command construction, synthetic
phase accounting, missing-data handling, completion-marker checks and plot
rendering. No C++ build or actual simulation was performed during creation.
