# Experiment 7: multipath parking lot with lane-local competition

Two lanes, each containing three serial 100 Mbps core links. The spine crosses
all three links in either lane; rib i crosses only link i in either lane.
Every original connection has two edge-disjoint alternatives.

- Symmetric: no background traffic, a control for multi-bottleneck fairness.
- LaneShift: five single-path connections join lane 1's middle link at 30 s,
  stop admission at 60 s; five new connections join lane 2's middle link at
  90 s and stop admission at 120 s. All runs end at 150 s.

Unlike the old mirrored RTT sweep, this gives the spine and middle rib a reason
to change lanes. The spine's movement also changes competition for the outer
ribs. Equal RTTs isolate redistribution before introducing RTT asymmetry.

Ideal full-capacity connection max-min rates in the symmetric case are 100 Mbps
each. During either wave, the five backgrounds can receive 20 Mbps each; spine
and middle rib receive 50 Mbps each on the other middle link, and the outer ribs
receive 150 Mbps each. These are topology references, not CC predictions.

All participants use the selected CC: Alpha, Delta, Omega,
OrbCC uncoupled, CUBIC uncoupled (also plot order). Five paired seeds; 20 ms
propagation RTT; 10 Gbps access legs; 173-packet core queues (one BDP at MSS 1448).
`defaultCwnd` throughout. Only forward core bottlenecks participate in shuffle;
access/reverse queues are ordinary DropTail queues. Exact INT/full feedback.
Background stop means admission stops; already admitted bytes may drain.

Plots include per-connection goodput with ideal references; source-interface
subflow wire rates; core-link busy fractions; cwnd, U, send queues and receiver
HoL; background goodput; per-case algorithm comparisons; mean +/- sample SD and
variance across runs. U is not plotted as link busy fraction. Wire rates include
protocol headers and are not application goodput. Interface order labels paths
without assuming connection-ID ordering. Non-INT algorithms have no U samples.
Only these diagnostic vectors are enabled; the vector catch-all remains false.

Phase summaries use the final ten seconds of each phase, require 95% sample
coverage, and do not fill missing goodput tails. New config/output names separate
these cases from old results. Old INIs are retained with `.ini.retired` suffixes;
raw results and plots were not deleted. Plot only the new case folders/comparisons.

Run from the OMNeT++ root:

```sh
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment7/runExperiment7.py --resume
```

Default simulations: 60. Wall-clock timeout: five hours per run.
No simulation was run when installing this revision.
