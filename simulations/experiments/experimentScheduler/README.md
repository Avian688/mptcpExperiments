# Four-algorithm scheduler comparison

Current matrix: Alpha, uncoupled OrbCC, uncoupled CUBIC and Delta; five seeds
for RTT profiles 20/20 and 60/20 ms. MpORB algorithms test default, defaultCwnd
and intInformed; CUBIC tests the first two only (intInformed requires MpORB).
Total: 110 simulations. Backgrounds use the same CC as the tested connection.
Their scheduler remains default. Delta shuffle is confined to the two forward
100 Mbps bottlenecks, with 5% budget and average-RTT intervals.

Five competitors join path 2 at 40 s and stop admission at 80 s; runs last 120 s.
Queues remain 173 packets. Plots are separated by CC under the main experiment
plot directory and retain scheduler, RTT, goodput, cwnd and HoL comparisons.

```sh
.venv/bin/python3 samples/mptcpExperiments/simulations/pythonScripts/experimentScheduler/runExperimentScheduler.py --cores 10 --resume --skip-generate
```

Each config is `<CC>_<equal|reversed>_<scheduler>_Run<N>` where CC is Alpha,
OrbUncoupled, CubicUncoupled or Delta. Select prefixes without `_Run<N>` using
`--configs`. Existing Alpha output data retain their CSV directory names.
