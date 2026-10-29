# Experiment 6: redistribution chain

Four separate 100 Mbps bottlenecks. A can use L1/L2, B L2/L3, C L3/L4;
D uses only L4. A/B/C each have two edge-disjoint alternatives; D deliberately
anchors the end of the chain. One single-path connection joins L1 at 30 s and
stops admitting data at 90 s. The experiment ends at 150 s.

This asks whether A moving to L2 causes B to move to L3 and C to move to L4,
while protecting connections with fewer alternatives. Ideal full-capacity
connection max-min rates are 100 Mbps each initially and 80 Mbps for all five
connections during competition. One feasible allocation in that phase is
A=(20,60), B=(40,40), C=(60,20), D=80, background=80 Mbps.

All participants use the selected CC: Alpha, Omega, Sender Delta, Theta,
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
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment6/runExperiment6.py --resume
```

Default simulations: 30. Wall-clock timeout: five hours per run.
No simulation was run when installing this revision.
