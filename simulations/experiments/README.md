# MPTCP / MpORB experiments

Experiments 1–7 and the existing named transport suites use: **Alpha, Omega, Sender Delta, Theta,
OrbCC uncoupled, CUBIC uncoupled**, in that order. All participants, including
single-path backgrounds, use the selected CC. Five paired seeds per case.
Numbered experiments use defaultCwnd. No CC implementation changed here.

| Experiment | Setup and aim | Runs |
| --- | --- | ---: |
| 1 | Two busy paths, competition and recovery; RTT (20, 20–200) ms. | 300 |
| 2 | Static ABC shared/private alternatives. | 30 |
| 3 | Two paths with temporary competition on one. | 30 |
| 4 | ABC with two temporary background waves. | 30 |
| 5 | Serial shared links plus a private 20 Mbps route; distinguishes fairness objectives. | 30 |
| 6 | A=(L1,L2), B=(L2,L3), C=(L3,L4), D=L4; L1 background tests a redistribution chain. | 30 |
| 7 | Symmetric parking-lot control and lane-local background waves; tests multipath movement across multi-bottleneck paths. | 60 |
| 8 | One LEO connection, three city pairs, requested K=1–5. | 300 |
| 9 | Two LEO connections on separate colocated terminal pairs, equal requested K. | 300 |
| 10 | Experiment 9 plus five one-subflow shortest-path backgrounds. | 300 |

Experiments 8–10 use **OrbCC uncoupled, Alpha, Omega, CUBIC uncoupled**.
See [LEO.md](LEO.md) for the shared layout, reuse of the original saved core
K paths, missing-path treatment, and validation limits.

See experiment6/README.md and experiment7/README.md for new topologies, timings,
references and diagnostics. Both use 100 Mbps bottlenecks and 20 ms RTTs.
Sender Delta, Omega and Theta measure shuffle only at explicit forward
bottlenecks. Their feedback is accepted only for the chosen highest-U bottleneck.
The 5% coefficient is not a hard sender-side interval budget. Other queue
settings and CC implementations retain their existing behaviour.

Run from `/Users/av288/omnetpp-6.4.0`:

```sh
for n in 4 5 6 7; do .venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment${n}/runExperiment${n}.py --resume || break; done
```

150 simulations across experiments 4–7. `--cores` controls concurrency; omission
uses the machine CPU limit and the extraction RAM budget. `--skip-generate`
keeps existing INI edits; omit it to use current generators. Timeout is five
hours per simulation. New 6/7 case names avoid reusing obsolete extracted data.
Retired variants remain recoverable as `.ini.retired`, not active inputs.
Existing results and plots are preserved, but only selected protocols/cases
enter new comparisons.

The named Test, Scheduler and MpOrbKShortestPaths experiments also use these
six algorithms. Scheduler retains its scheduler/RTT comparisons (CUBIC excludes
intInformed); Test retains its 20 Mbps ABC setup. MpOrbKShortestPaths has six
batches (`alpha`, `omega`, `senderdelta`, `theta`, `uncoupled`, `cubic`): 750 runs.
The routing-only experimentKShortestPaths uses ping and has no transport matrix.

Validation covers generated matrices, NED syntax, config selection and synthetic
plots, not runtime protocol behaviour. All default catch-all vector recording
remains false; only selected diagnostics are enabled.

## Extraction memory and CPU use

`--cores` remains the maximum parallelism, including extraction. The extractors
stream CSV-R in fixed-size blocks, skip unselected vectors, and preserve selected
numeric text without building whole-file pandas/NumPy objects. Even a single
very large vector is streamed through temporary files. Metric selections, output
paths and plot inputs are unchanged. K-shortest-path summaries use disk-backed
arrays and bounded batches because they also calculate statistics. Temporary
files are cleaned up on success or handled failure; allow scratch disk space for
the selected vector (or the selected run's arrays for K-shortest-path extraction).

Before each extraction stage/retry, workers are selected from the requested core
count, job count, and available RAM. Each worker reserves 256 MiB in the scheduling
calculation. At most 70% of available RAM is budgeted, leaving at least 1 GiB free.
This permits 30 workers when the budget is at least 7.5 GiB, rather than imposing
a fixed small worker count. This reservation is a scheduling estimate, not an
OS-enforced quota; unrelated processes can still change memory pressure mid-run.
`EXPERIMENT_EXTRACT_MEMORY_GIB` optionally sets a smaller total extraction budget.
If RAM availability cannot be read, it supplies the explicit budget instead;
otherwise the default fallback is one worker. Simulation/export parallelism is
unchanged.

To re-extract existing Experiment 6 exports without rerunning simulations or
regenerating INIs, from the OMNeT++ root:

```sh
.venv/bin/python3 samples/mptcpExperiments/simulations/pythonScripts/experiment6/runExperiment6.py --start-step 3 --skip-generate --cores 30
```

Synthetic checks cover quoted CSV fields across block boundaries, wide/long
layouts, metric selection, numeric precision, thread-name collisions and worker
selection. A local sequential comparison against the former pandas approach
measured 0.36–0.80 s and 39–42 MiB peak RSS, versus 2.31–2.99 s and 171–258 MiB,
for 42–81 MiB inputs (mostly unused vectors, all selected vectors, and one large
vector). Numeric outputs matched exactly. These are synthetic measurements,
not a throughput guarantee for full runs or concurrent disk workloads.
