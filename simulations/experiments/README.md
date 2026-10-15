# MPTCP / MpORB experiments

The transport comparison suite selects five algorithms:
**Alpha**, **Delta**, **Omega**, **OrbCC uncoupled**, then **CUBIC uncoupled**.
This is also the plotting order. Omega is sender-side Delta with RTT-scaled underutilisation AI.
Delta inherits Alpha and adds the existing switch shuffle. The experiment setup
changes neither congestion-control implementation nor its gain.
All participants in a run use its selected CC, including single-subflow backgrounds.
Numbered experiments use `defaultCwnd`. Five paired seeds are used per case.

| Experiment | Setup and aim | Default simulations |
| --- | --- | ---: |
| 1 | A uses two busy 100 Mbps paths, B/C use one each; four competitors join path 2 at 60 s and stop admission at 120 s. Path 1 RTT is 20 ms, path 2 sweeps 20–200 ms. Tests redistribution/recovery and RTT sensitivity; 240 s. | 250 |
| 2 | Static ABC: A=(1,2,3,4), B=(1,2,5,6), C=(3,4,7,8). Tests sharing versus private alternatives. | 25 |
| 3 | Two 100 Mbps paths; five competitors join path 2 at 40 s and stop admission at 80 s. Tests responsiveness and HoL. | 25 |
| 4 | ABC with background waves at 30–60 s on paths 5/6 and 90–120 s on paths 1/2. Tests redistribution between interacting connections; 150 s. | 25 |
| 5 | A traverses two shared 100 Mbps links in series or its private 20 Mbps link; B/C each use one shared link. Tests allocation objectives; 300 s. | 25 |
| 6 | ABC with simultaneous starts, A first, or B/C first; later arrivals join around 60 s. Tests arrival-order dependence; 300 s. | 75 |
| 7 | Two independent three-link parking-lot lanes; spine and three ribs each have two subflows. Tests multi-bottleneck fairness over RTTs 20–200 ms. | 250 |

Experiment 5's ideal connection max–min reference is (60,60,60) Mbps;
proportional fairness is (40,80,80). Experiment 7's references are 100 Mbps each
for max–min versus spine=50, ribs=150 Mbps for proportional fairness.
These are full-capacity references, not claimed properties of the algorithms.

## Delta and Omega queue scope

Only explicitly listed forward bottleneck egress queues issue shuffle:

- Experiments 1/3: `p1Ingress.ppp[0]`, `p2Ingress.ppp[0]`.
- Experiments 2/4/6: the eight `router1` core-link egresses (PPP 2 on paths 1–4,
  PPP 1 on paths 5–8).
- Experiment 5: `left.ppp[0]`, `middle.ppp[1]`, `privateIngress.ppp[0]`.
- Experiment 7: the three forward core egresses in each lane.

Specific Delta assignments precede the wildcard zero fallback (OMNeT++ uses the
first matching key). Omega uses the same allowlist for sender-side fairness feedback.
Access/reverse queues issue no shuffle. Alpha and uncoupled CC cases
have shuffle disabled everywhere. Delta uses a 0.05 sum-of-absolute-rate-change
budget per link round and `deltaShuffleInterval=0s` to follow the queue average
RTT. `deltaNeedGain` retains its queue/NED default.
Omega retains the 0.05 coefficient scale without the switch-side hard budget.
Both use only the chosen highest-U bottleneck feedback at the sender.
The private route in experiment 5 is also a capacity-limiting link and participates.

Experiment 4 preserves the editable NED bottleneck capacity (currently 100 Mbps),
with one-BDP packet buffers calculated from that capacity and its 40 ms RTT.
It now generates genuine Alpha and separate Delta files, instead of running
Delta under an Alpha name. Both waves fit inside every generated 150 s run.
Background stop events disable new admission; already admitted data may drain.

## Run experiments 4–7

From `/Users/av288/omnetpp-6.4.0`, with the normal built libraries and Python
plotting environment:

```sh
for n in 4 5 6 7; do .venv/bin/python3 samples/mptcpExperiments/simulations/pythonScripts/experiment${n}/runExperiment${n}.py --cores 10 --resume --skip-generate || break; done
```

This selects all five algorithms: 375 simulations total. Omit `--skip-generate`
to regenerate the checked-in inputs. Each runner covers simulation, export,
extraction and plotting; `--cores` controls workers. Existing results are retained.
`--resume` uses the runner's completion checks; changed inputs can invalidate old runs.
Retired protocol INIs/results may remain on disk but are not selected by the runners
or comparison plots. Generated filenames/configs are listed by the runner modules.

## Separately named experiments

- `experimentScheduler`: five CCs across equal/reversed RTT profiles; compares
  default/defaultCwnd/intInformed. CUBIC uses only default/defaultCwnd because
  intInformed belongs to MpOrbConnection. 110 simulations, plots separated by CC.
  Delta shuffle is enabled only on the two forward bottlenecks.
- `experimentKShortestPaths`: routing/ping experiment; no CC selection needed.
- `experimentMpOrbKShortestPaths`: five batches (`alpha`, `delta`, `omega`, `uncoupled`,
  `cubic`), five city pairs, K=1–5, five seeds: 500 simulations. Uses defaultCwnd.
  Unlike the fixed topologies, all LEO physical links are 100 Mbps, including
  access links; all physical egress queues are potential bottlenecks. Delta is
  enabled on satellite/ground-station/terminal PPP queues with a zero fallback.

Validation: input generation, Python checks, runner selection and OMNeT++
configuration queries. These checks do not establish runtime protocol performance.

Runner wall-clock timeout defaults to five hours (18,000 s), overridable with
`--sim-timeout-seconds` or `EXPERIMENT_SIM_TIMEOUT_SECONDS`. Simulation durations
are unchanged. Allocation comparisons use separate connection panels and consistent
algorithm colours; means and sample SD are computed across repetitions.

## Plot comparisons

Experiment 4 wraps the uncoupled CC labels and uses wider heatmap panels.
Experiment 6 writes `allocation_comparison_Together`, `allocation_comparison_AFirst`,
and `allocation_comparison_BCFirst` (PNG/PDF), replacing the old combined allocation
plot. Each figure shows separate A/B/C panels, individual runs and mean ± sample
SD, with the same goodput scale across arrival cases. All CC comparisons follow
the order above. Experiment 7 retains its layout and plots all five algorithms.

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
