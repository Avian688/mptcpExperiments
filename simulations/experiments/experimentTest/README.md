# experimentTest: 20 Mbps dynamic ABC

Copy of experiment 4, with eight 20 Mbps bottlenecks, 40 ms propagation RTT,
10 Gbps access links and one-BDP buffers (70 packets at MSS 1448).
A uses paths 1–4; B uses 1,2,5,6; C uses 3,4,7,8.

| Time | Background load |
| --- | --- |
| 0–20 s | None; A/B/C start at the same seeded times in 0–5 s |
| 20–40 s | Five one-subflow connections on each of B's paths 5 and 6 |
| 40–60 s | Background admission disabled; recovery |
| 60–80 s | Five new one-subflow connections on each shared A/B path 1 and 2 |
| 80–100 s | Background admission disabled; recovery |

Stopping admission lets already queued/in-flight traffic drain, as in experiment 4.
All connections use the selected algorithm. Five repetitions each of Alpha,
uncoupled OrbCC, uncoupled CUBIC, switch-side Delta, sender-side Delta and Omega use
`defaultCwnd`. Delta measurements/shuffling are enabled only at the eight
forward bottlenecks. Other experiments and their protocol matrices are unchanged.

From the simulations directory, run/export/extract/plot all 30 runs:

```sh
python3 pythonScripts/experimentTest/runExperimentTest.py --cores 10
```

For just the new sender-side Delta (five runs):

```sh
python3 pythonScripts/experimentTest/runExperimentTest.py --cores 10 --configs MpOrbSenderDelta
```

Runner timeout remains five hours per simulation. Results, logs and plots use
experimentTest directories. Plots include per-run responses and phase goodput
comparisons with mean and sample SD over the final 10 seconds of each phase.
The runner regenerates inputs unless `--skip-generate` is supplied.
