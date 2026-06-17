#!/usr/bin/env python3

from __future__ import annotations

from html import escape
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
OUT_DIR = SIM_ROOT / "plots" / "diagrams"

COLOR = {
    "ink": "#0f172a",
    "muted": "#475569",
    "grid": "#cbd5e1",
    "panel": "#ffffff",
    "bg": "#f8fafc",
    "blue": "#2563eb",
    "blue_soft": "#dbeafe",
    "orange": "#f97316",
    "orange_soft": "#ffedd5",
    "green": "#16a34a",
    "green_soft": "#dcfce7",
    "purple": "#7c3aed",
    "purple_soft": "#ede9fe",
    "red": "#dc2626",
    "red_soft": "#fee2e2",
    "slate_soft": "#e2e8f0",
}


def tag(name: str, attrs: dict[str, str | int | float], content: str | None = None) -> str:
    attr = " ".join(f'{key}="{escape(str(value), quote=True)}"' for key, value in attrs.items() if value is not None)
    if content is None:
        return f"<{name} {attr}/>"
    return f"<{name} {attr}>{content}</{name}>"


def svg_doc(width: int, height: int, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            "  <defs>",
            "    <filter id=\"shadow\" x=\"-20%\" y=\"-20%\" width=\"140%\" height=\"140%\">",
            "      <feDropShadow dx=\"0\" dy=\"8\" stdDeviation=\"8\" flood-color=\"#0f172a\" flood-opacity=\"0.10\"/>",
            "    </filter>",
            "  </defs>",
            f'  <rect width="{width}" height="{height}" fill="{COLOR["bg"]}"/>',
            *body,
            "</svg>",
            "",
        ]
    )


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none", sw: float = 1, rx: float = 12, extra: str = "") -> str:
    attrs = {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "rx": rx,
        "fill": fill,
        "stroke": stroke,
        "stroke-width": sw,
    }
    out = tag("rect", attrs)
    if extra:
        out = out.replace("/>", f" {extra}/>")
    return out


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, sw: float = 3, dash: str | None = None, opacity: float = 1.0) -> str:
    attrs = {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "stroke": stroke,
        "stroke-width": sw,
        "stroke-linecap": "round",
        "opacity": opacity,
    }
    if dash:
        attrs["stroke-dasharray"] = dash
    return tag("line", attrs)


def path(d: str, stroke: str, sw: float = 3, fill: str = "none", dash: str | None = None, opacity: float = 1.0) -> str:
    attrs = {
        "d": d,
        "stroke": stroke,
        "stroke-width": sw,
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
        "fill": fill,
        "opacity": opacity,
    }
    if dash:
        attrs["stroke-dasharray"] = dash
    return tag("path", attrs)


def text(x: float, y: float, value: str, size: int = 24, fill: str = COLOR["ink"], weight: int = 500, anchor: str = "start") -> str:
    attrs = {
        "x": x,
        "y": y,
        "font-family": "Inter, Helvetica, Arial, sans-serif",
        "font-size": size,
        "font-weight": weight,
        "fill": fill,
        "text-anchor": anchor,
    }
    return tag("text", attrs, escape(value))


def multiline(x: float, y: float, lines: list[str], size: int = 20, fill: str = COLOR["muted"], weight: int = 500, leading: int = 28) -> list[str]:
    return [text(x, y + i * leading, item, size=size, fill=fill, weight=weight) for i, item in enumerate(lines)]


def node(x: float, y: float, w: float, h: float, title: str, subtitle: str, stroke: str, fill: str = "#ffffff") -> list[str]:
    return [
        rect(x, y, w, h, fill, stroke, 2.2, 18, 'filter="url(#shadow)"'),
        text(x + w / 2, y + 34, title, size=22, fill=COLOR["ink"], weight=800, anchor="middle"),
        text(x + w / 2, y + 62, subtitle, size=16, fill=COLOR["muted"], weight=600, anchor="middle"),
    ]


def label_box(x: float, y: float, lines: list[str], fill: str, stroke: str, w: float = 300, h: float | None = None) -> list[str]:
    h = h if h is not None else 34 + 26 * len(lines)
    body = [rect(x, y, w, h, fill, stroke, 1.5, 14)]
    body.extend(multiline(x + 18, y + 32, lines, size=17, fill=COLOR["ink"], weight=650, leading=24))
    return body


def pill(x: float, y: float, label: str, fill: str, stroke: str, text_fill: str = COLOR["ink"], w: float | None = None) -> list[str]:
    width = w if w is not None else max(52, 20 + len(label) * 10)
    return [
        rect(x, y, width, 28, fill, stroke, 1.2, 14),
        text(x + width / 2, y + 20, label, size=15, fill=text_fill, weight=800, anchor="middle"),
    ]


def generate_experiment1() -> Path:
    body: list[str] = []
    body.append(text(70, 58, "Experiment 1: Scheduler Negatives on Two LEO-Like Paths", size=34, weight=850))
    body.extend(
        multiline(
            70,
            94,
            [
                "One MPTCP/MPORB connection, two subflows. Path 0 is fixed and narrow; Path 1 is high-capacity with swept RTT.",
                "Goal: expose scheduler-induced reordering / HoL blocking when subflows have very different delay-capacity profiles.",
            ],
            size=19,
            leading=26,
        )
    )

    body.extend(node(90, 360, 150, 92, "Client[0]", "1 app", COLOR["ink"]))
    body.extend(node(1160, 360, 150, 92, "Server[0]", "sink", COLOR["ink"]))
    body.extend(node(350, 215, 130, 84, "R1a", "path 0", COLOR["blue"], COLOR["blue_soft"]))
    body.extend(node(810, 215, 130, 84, "R2a", "path 0", COLOR["blue"], COLOR["blue_soft"]))
    body.extend(node(350, 525, 130, 84, "R1b", "path 1", COLOR["orange"], COLOR["orange_soft"]))
    body.extend(node(810, 525, 130, 84, "R2b", "path 1", COLOR["orange"], COLOR["orange_soft"]))

    # Fixed path.
    body.append(line(240, 392, 350, 257, COLOR["blue"], 5, opacity=0.85))
    body.append(line(480, 257, 810, 257, COLOR["blue"], 9, opacity=0.9))
    body.append(line(940, 257, 1160, 392, COLOR["blue"], 5, opacity=0.85))
    body.extend(label_box(540, 135, ["Path 0 fixed", "RTT 20 ms | 10 Mbps", "Q = 1554 packets"], COLOR["blue_soft"], COLOR["blue"], w=290, h=98))
    body.append(rect(622, 248, 64, 22, "#ffffff", COLOR["blue"], 1.5, 6))
    body.append(text(654, 264, "Q", size=16, fill=COLOR["blue"], weight=850, anchor="middle"))
    body.append(text(302, 300, "5 ms access", size=15, fill=COLOR["blue"], weight=750, anchor="middle"))
    body.append(text(1020, 307, "5 ms access", size=15, fill=COLOR["blue"], weight=750, anchor="middle"))

    # Variable path.
    body.append(line(240, 420, 350, 567, COLOR["orange"], 5, opacity=0.85))
    body.append(line(480, 567, 810, 567, COLOR["orange"], 9, opacity=0.9))
    body.append(line(940, 567, 1160, 420, COLOR["orange"], 5, opacity=0.85))
    body.extend(label_box(540, 625, ["Path 1 swept", "RTT 20-180 ms | 100 Mbps", "Q = 1554 packets"], COLOR["orange_soft"], COLOR["orange"], w=330, h=98))
    body.append(rect(622, 558, 64, 22, "#ffffff", COLOR["orange"], 1.5, 6))
    body.append(text(654, 574, "Q", size=16, fill=COLOR["orange"], weight=850, anchor="middle"))
    body.append(text(302, 533, "5-45 ms access", size=15, fill=COLOR["orange"], weight=750, anchor="middle"))
    body.append(text(1030, 533, "5-45 ms access", size=15, fill=COLOR["orange"], weight=750, anchor="middle"))

    body.extend(label_box(70, 675, ["Sweep configs", "RTT: 20, 40, ..., 180 ms", "Protocols: CUBIC, MPORB", "Schedulers: default, lowestRTT, directPull"], "#ffffff", COLOR["grid"], w=390, h=136))
    body.extend(label_box(910, 675, ["Recorded outputs", "aggregate goodput", "per-subflow goodput", "HoL blocked bytes", "DSN gap at receiver"], "#ffffff", COLOR["grid"], w=390, h=136))

    body.append(rect(500, 748, 380, 78, COLOR["red_soft"], COLOR["red"], 1.5, 14))
    body.append(text(690, 773, "Failure signal", size=18, fill=COLOR["red"], weight=850, anchor="middle"))
    body.append(text(690, 797, "High subflow throughput", size=15, fill=COLOR["ink"], weight=650, anchor="middle"))
    body.append(text(690, 818, "but lower app goodput / receiver HoL", size=15, fill=COLOR["ink"], weight=650, anchor="middle"))

    out = OUT_DIR / "experiment1_setup.svg"
    out.write_text(svg_doc(1400, 860, body), encoding="utf-8")
    return out


def generate_experiment2() -> Path:
    body: list[str] = []
    body.append(text(70, 58, "Experiment 2: Uncoupled Fairness over Shared LEO Paths", size=34, weight=850))
    body.extend(
        multiline(
            70,
            94,
            [
                "Three users, four subflows each, eight 100 Mbps paths with staggered RTTs.",
                "Goal: show uncoupled per-subflow control lets users with private paths win over a user whose paths are all shared.",
            ],
            size=19,
            leading=26,
        )
    )

    user_colors = {
        "A": (COLOR["blue"], COLOR["blue_soft"]),
        "B": (COLOR["green"], COLOR["green_soft"]),
        "C": (COLOR["purple"], COLOR["purple_soft"]),
    }
    for i, (user, desc) in enumerate(
        [
            ("A", "paths 1-4; all shared"),
            ("B", "paths 1,2,5,6"),
            ("C", "paths 3,4,7,8"),
        ]
    ):
        x = 70 + i * 350
        stroke, fill = user_colors[user]
        body.extend(pill(x, 160, f"User {user}", fill, stroke, w=95))
        body.append(text(x + 110, 181, desc, size=16, fill=COLOR["muted"], weight=650))

    body.extend(label_box(1220, 142, ["Configs", "CubicUncoupled", "MpOrbUncoupled", "4 subflows per user"], "#ffffff", COLOR["grid"], w=320, h=116))
    body.extend(label_box(1220, 278, ["Common path settings", "100 Mbps each", "RTT 60-130 ms", "1 BDP buffer = 1123 packets"], "#ffffff", COLOR["grid"], w=320, h=116))

    # Path pool.
    body.append(text(70, 250, "LEO Path Pool", size=25, fill=COLOR["ink"], weight=850))
    body.append(text(70, 282, "Each row is one router1[i] -> router2[i] bottleneck. Colored chips show which users put subflows on it.", size=17, fill=COLOR["muted"], weight=600))
    paths = [
        (1, 60, ["A", "B"], "shared A+B"),
        (2, 70, ["A", "B"], "shared A+B"),
        (3, 80, ["A", "C"], "shared A+C"),
        (4, 90, ["A", "C"], "shared A+C"),
        (5, 100, ["B"], "private to B"),
        (6, 110, ["B"], "private to B"),
        (7, 120, ["C"], "private to C"),
        (8, 130, ["C"], "private to C"),
    ]
    y0 = 315
    row_h = 48
    for idx, rtt, users, note in paths:
        y = y0 + (idx - 1) * row_h
        fill = "#ffffff" if idx % 2 else "#f1f5f9"
        body.append(rect(70, y, 1120, 38, fill, COLOR["grid"], 1, 8))
        body.append(text(92, y + 25, f"P{idx}", size=18, fill=COLOR["ink"], weight=850))
        body.append(text(155, y + 25, f"{rtt} ms RTT", size=16, fill=COLOR["muted"], weight=700))
        body.append(line(285, y + 19, 720, y + 19, COLOR["ink"], 5, opacity=0.25))
        body.append(rect(450, y + 8, 112, 22, COLOR["slate_soft"], COLOR["muted"], 1, 6))
        body.append(text(506, y + 24, "100 Mbps", size=14, fill=COLOR["ink"], weight=800, anchor="middle"))
        body.append(text(755, y + 25, "Q=1123 pkts", size=15, fill=COLOR["muted"], weight=700))
        chip_x = 900
        for user in users:
            stroke, chip_fill = user_colors[user]
            body.extend(pill(chip_x, y + 5, user, chip_fill, stroke, text_fill=stroke, w=36))
            chip_x += 44
        note_color = COLOR["red"] if note.startswith("shared") else COLOR["muted"]
        body.append(text(1080, y + 25, note, size=15, fill=note_color, weight=750, anchor="middle"))

    # Assignment matrix.
    matrix_x = 70
    matrix_y = 735
    body.append(text(matrix_x, matrix_y - 25, "User-to-Path Assignment Matrix", size=24, fill=COLOR["ink"], weight=850))
    cell_w = 78
    cell_h = 42
    body.append(rect(matrix_x, matrix_y, 4 * cell_w + 5 * cell_w, 4 * cell_h, "#ffffff", COLOR["grid"], 1.4, 12))
    for col in range(8):
        x = matrix_x + cell_w + col * cell_w
        body.append(text(x + cell_w / 2, matrix_y + 28, f"P{col + 1}", size=16, fill=COLOR["ink"], weight=850, anchor="middle"))
    assignment = {
        "A": {1, 2, 3, 4},
        "B": {1, 2, 5, 6},
        "C": {3, 4, 7, 8},
    }
    for row, user in enumerate(["A", "B", "C"], start=1):
        y = matrix_y + row * cell_h
        stroke, fill = user_colors[user]
        body.append(text(matrix_x + 38, y + 28, f"User {user}", size=16, fill=stroke, weight=850, anchor="middle"))
        for col in range(8):
            x = matrix_x + cell_w + col * cell_w
            body.append(rect(x + 8, y + 7, cell_w - 16, cell_h - 14, fill if (col + 1) in assignment[user] else "#ffffff", stroke if (col + 1) in assignment[user] else COLOR["grid"], 1.2, 8))
            if (col + 1) in assignment[user]:
                body.append(text(x + cell_w / 2, y + 27, "subflow", size=12, fill=stroke, weight=850, anchor="middle"))

    # Expected result callout.
    body.append(rect(910, 745, 620, 160, COLOR["red_soft"], COLOR["red"], 1.6, 16))
    body.append(text(1220, 777, "Expected uncoupled failure", size=22, fill=COLOR["red"], weight=850, anchor="middle"))
    body.extend(
        multiline(
            950,
            810,
            [
                "A has four subflows, like B and C,",
                "but every A path is shared.",
                "B and C each get two private paths,",
                "so A should see lower aggregate goodput.",
            ],
            size=17,
            fill=COLOR["ink"],
            weight=650,
            leading=24,
        )
    )

    out = OUT_DIR / "experiment2_setup.svg"
    out.write_text(svg_doc(1600, 950, body), encoding="utf-8")
    return out


def write_notes() -> Path:
    out = OUT_DIR / "README.md"
    out.write_text(
        "\n".join(
            [
                "# MPTCP Experiment Diagrams",
                "",
                "Generated meeting diagrams for the two `mptcpExperiments` setups.",
                "",
                "## Experiment 1",
                "",
                "- One user, two subflows.",
                "- Path 0: fixed 20 ms RTT, 10 Mbps bottleneck.",
                "- Path 1: swept 20-180 ms RTT, 100 Mbps bottleneck.",
                "- Queue size: 1554 packets, based on the highest swept BDP.",
                "- Compare CUBIC and MPORB across default, lowestRTT, and directPull schedulers.",
                "- Metrics: aggregate goodput, per-subflow goodput, HoL blocked bytes, DSN gap.",
                "",
                "## Experiment 2",
                "",
                "- Three users, four subflows each.",
                "- Eight LEO-like paths, all 100 Mbps, RTTs 60-130 ms.",
                "- Queue size: 1123 packets, based on the highest path BDP.",
                "- User A uses paths 1-4; B uses 1,2,5,6; C uses 3,4,7,8.",
                "- Expected uncoupled failure: A gets less aggregate goodput because all of A's paths are shared.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = [generate_experiment1(), generate_experiment2(), write_notes()]
    for path in generated:
        print(path)


if __name__ == "__main__":
    main()
