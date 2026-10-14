# MPTCP / MpORB experiments

The transport comparison suite selects exactly four algorithms:
**Alpha**, **OrbCC uncoupled**, **CUBIC uncoupled**, and **Delta**.
Delta inherits Alpha and adds the existing switch shuffle. The experiment setup
changes neither congestion-control implementation nor its gain.
All participants in a run use its selected CC, including single-subflow backgrounds.
Numbered experiments use `defaultCwnd`. Five paired seeds are used per case.

| Experiment | Setup and aim | Default simulations |
| --- | --- | ---: |
| 1 | A uses two busy 100 Mbps paths, B/C use one each; four competitors join path 2 at 60 s and stop admission at 120 s. Path 1 RTT is 20 ms, path 2 sweeps 20–200 ms. Tests redistribution/recovery and RTT sensitivity; 240 s. | 200 |
| 2 | Static ABC: A=(1,2,3,4), B=(1,2,5,6), C=(3,4,7,8). Tests sharing versus private alternatives. | 20 |
| 3 | Two 100 Mbps paths; five competitors join path 2 at 40 s and stop admission at 80 s. Tests responsiveness and HoL. | 20 |
| 4 | ABC with background waves at 30–60 s on paths 5/6 and 90–120 s on paths 1/2. Tests redistribution between interacting connections; 150 s. | 20 |
| 5 | A traverses two shared 100 Mbps links in series or its private 20 Mbps link; B/C each use one shared link. Tests allocation objectives; 300 s. | 20 |
| 6 | ABC with simultaneous starts, A first, or B/C first; later arrivals join around 60 s. Tests arrival-order dependence; 300 s. | 60 |
| 7 | Two independent three-link parking-lot lanes; spine and three ribs each have two subflows. Tests multi-bottleneck fairness over RTTs 20–200 ms. | 200 |

Experiment 5's ideal connection max–min reference is (60,60,60) Mbps;
proportional fairness is (40,80,80). Experiment 7's references are 100 Mbps each
for max–min versus spine=50, ribs=150 Mbps for proportional fairness.
These are full-capacity references, not claimed properties of the algorithms.

## Delta queue scope

Only explicitly listed forward bottleneck egress queues issue shuffle:

- Experiments 1/3: `p1Ingress.ppp[0]`, `p2Ingress.ppp[0]`.
- Experiments 2/4/6: the eight `router1` core-link egresses (PPP 2 on paths 1–4,
  PPP 1 on paths 5–8).
- Experiment 5: `left.ppp[0]`, `middle.ppp[1]`, `privateIngress.ppp[0]`.
- Experiment 7: the three forward core egresses in each lane.

Specific Delta assignments precede the wildcard zero fallback (OMNeT++ uses the
first matching key). Access/reverse queues issue no shuffle. Other CC cases
have shuffle disabled everywhere. Delta uses a 0.05 sum-of-absolute-rate-change
budget per link round and `deltaShuffleInterval=0s` to follow the queue average
RTT. `deltaNeedGain` retains its queue/NED default.
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

This selects all four algorithms: 300 simulations total. Omit `--skip-generate`
to regenerate the checked-in inputs. Each runner covers simulation, export,
extraction and plotting; `--cores` controls workers. Existing results are retained.
`--resume` uses the runner's completion checks; changed inputs can invalidate old runs.
Retired protocol INIs/results may remain on disk but are not selected by the runners
or comparison plots. Generated filenames/configs are listed by the runner modules.

## Separately named experiments

- `experimentScheduler`: four CCs across equal/reversed RTT profiles; compares
  default/defaultCwnd/intInformed. CUBIC uses only default/defaultCwnd because
  intInformed belongs to MpOrbConnection. 110 simulations, plots separated by CC.
  Delta shuffle is enabled only on the two forward bottlenecks.
- `experimentKShortestPaths`: routing/ping experiment; no CC selection needed.
- `experimentMpOrbKShortestPaths`: four batches (`alpha`, `uncoupled`, `cubic`,
  `delta`), five city pairs, K=1–5, five seeds: 500 simulations. Uses defaultCwnd.
  Unlike the fixed topologies, all LEO physical links are 100 Mbps, including
  access links; all physical egress queues are potential bottlenecks. Delta is
  enabled on satellite/ground-station/terminal PPP queues with a zero fallback.

Validation: input generation, Python checks, runner selection and OMNeT++
configuration queries. These checks do not establish runtime protocol performance.

Runner wall-clock timeout defaults to five hours (18,000 s), overridable with
`--sim-timeout-seconds` or `EXPERIMENT_SIM_TIMEOUT_SECONDS`. Simulation durations
are unchanged. Allocation comparisons use separate connection panels and consistent
algorithm colours; means and sample SD are computed across repetitions.
