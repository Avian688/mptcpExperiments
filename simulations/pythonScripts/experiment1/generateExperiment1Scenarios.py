#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

RTT_SWEEP_MS = [20, 40, 60, 80, 100, 120, 140, 160, 180]
FIXED_PATH_RTT_MS = 20
FIXED_PATH_DATARATE = "10Mbps"
VARIABLE_PATH_DATARATE = "100Mbps"
ACCESS_DATARATE = "10Gbps"


SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
SCENARIO_DIR = SIM_ROOT / "experiments" / "scenarios" / "experiment1"


def fmt_ms(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}ms"
    return f"{value:g}ms"


def write_scenario(path: Path, variable_rtt_ms: int) -> None:
    fixed_access_delay = fmt_ms(FIXED_PATH_RTT_MS / 4)
    variable_access_delay = fmt_ms(variable_rtt_ms / 4)

    with path.open("w", encoding="utf-8") as f:
        def w(line: str = "") -> None:
            f.write(line + "\n")

        w("<scenario>")
        w('    <at t="0">')
        w("        <!-- Path 0: fixed 20 ms RTT / 10 Mbps bottleneck. -->")
        w(f'        <set-channel-param src-module="client[0]" src-gate="pppg$o[0]" par="delay" value="{fixed_access_delay}"/>')
        w(f'        <set-channel-param src-module="router1a" src-gate="pppg$o[0]" par="delay" value="{fixed_access_delay}"/>')
        w(f'        <set-channel-param src-module="router2a" src-gate="pppg$o[0]" par="delay" value="{fixed_access_delay}"/>')
        w(f'        <set-channel-param src-module="server[0]" src-gate="pppg$o[0]" par="delay" value="{fixed_access_delay}"/>')
        w(f'        <set-channel-param src-module="router1a" src-gate="pppg$o[1]" par="datarate" value="{FIXED_PATH_DATARATE}"/>')
        w(f'        <set-channel-param src-module="router2a" src-gate="pppg$o[1]" par="datarate" value="{FIXED_PATH_DATARATE}"/>')
        w()
        w(f"        <!-- Path 1: swept {variable_rtt_ms} ms RTT / 100 Mbps bottleneck. -->")
        w(f'        <set-channel-param src-module="client[0]" src-gate="pppg$o[1]" par="delay" value="{variable_access_delay}"/>')
        w(f'        <set-channel-param src-module="router1b" src-gate="pppg$o[0]" par="delay" value="{variable_access_delay}"/>')
        w(f'        <set-channel-param src-module="router2b" src-gate="pppg$o[0]" par="delay" value="{variable_access_delay}"/>')
        w(f'        <set-channel-param src-module="server[0]" src-gate="pppg$o[1]" par="delay" value="{variable_access_delay}"/>')
        w(f'        <set-channel-param src-module="router1b" src-gate="pppg$o[1]" par="datarate" value="{VARIABLE_PATH_DATARATE}"/>')
        w(f'        <set-channel-param src-module="router2b" src-gate="pppg$o[1]" par="datarate" value="{VARIABLE_PATH_DATARATE}"/>')
        w()
        w("        <!-- Keep access links out of the bottleneck. -->")
        for module, gate in (
            ("client[0]", 0),
            ("client[0]", 1),
            ("router1a", 0),
            ("router1b", 0),
            ("router2a", 0),
            ("router2b", 0),
            ("server[0]", 0),
            ("server[0]", 1),
        ):
            w(f'        <set-channel-param src-module="{module}" src-gate="pppg$o[{gate}]" par="datarate" value="{ACCESS_DATARATE}"/>')
        w()
        w("        <update module=\"configurator\"/>")
        w("    </at>")
        w("</scenario>")


def main() -> None:
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    for rtt_ms in RTT_SWEEP_MS:
        write_scenario(SCENARIO_DIR / f"{rtt_ms}ms.xml", rtt_ms)
    print(f"Generated {len(RTT_SWEEP_MS)} experiment 1 scenario XML file(s) under {SCENARIO_DIR}.")


if __name__ == "__main__":
    main()
