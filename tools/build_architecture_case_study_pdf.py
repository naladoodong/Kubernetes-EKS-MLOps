#!/usr/bin/env python3
"""Build the ArgMax Mini AWS EKS architecture portfolio PDF."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = landscape(A4)
TOTAL_PAGES = 11

PAPER = HexColor("#F4F2EC")
WHITE = HexColor("#FFFFFF")
INK = HexColor("#111827")
INK_2 = HexColor("#23314D")
MUTED = HexColor("#586273")
FAINT = HexColor("#8790A0")
LINE = HexColor("#D7D8D4")
BLUE = HexColor("#2155D6")
BLUE_DARK = HexColor("#153A96")
BLUE_SOFT = HexColor("#E8EEFF")
CYAN = HexColor("#0E7490")
CYAN_SOFT = HexColor("#E3F4F7")
GREEN = HexColor("#176B4D")
GREEN_SOFT = HexColor("#E4F2EC")
AMBER = HexColor("#8A5B08")
AMBER_SOFT = HexColor("#F7EDCF")
RED = HexColor("#A63B3B")
RED_SOFT = HexColor("#F8E7E5")
PURPLE = HexColor("#6842A6")
PURPLE_SOFT = HexColor("#EEE8F7")
NAVY = HexColor("#101A2D")
NAVY_2 = HexColor("#172640")


def mix(color: Color, alpha: float) -> Color:
    return Color(color.red, color.green, color.blue, alpha=alpha)


def wrap_lines(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split()
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if stringWidth(candidate, font, size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_paragraph(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    *,
    font: str = "Helvetica",
    size: float = 9,
    leading: float | None = None,
    color: Color = INK,
    max_lines: int | None = None,
) -> float:
    leading = leading or size * 1.35
    lines = wrap_lines(text, font, size, width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and stringWidth(last + "...", font, size) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "..."
    c.setFillColor(color)
    c.setFont(font, size)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_bullets(
    c: canvas.Canvas,
    items: list[str],
    x: float,
    y: float,
    width: float,
    *,
    size: float = 8.2,
    leading: float = 10.5,
    color: Color = INK,
    dot_color: Color = BLUE,
    gap: float = 5,
) -> float:
    for item in items:
        c.setFillColor(dot_color)
        c.circle(x + 2.5, y + 2.5, 2.2, fill=1, stroke=0)
        y = draw_paragraph(
            c,
            item,
            x + 11,
            y,
            width - 11,
            size=size,
            leading=leading,
            color=color,
        )
        y -= gap
    return y


def rounded_rect(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: Color = WHITE,
    stroke: Color = LINE,
    radius: float = 10,
    line_width: float = 0.8,
) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def badge(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    *,
    bg: Color = BLUE_SOFT,
    fg: Color = BLUE_DARK,
    size: float = 7.2,
    height: float = 18,
    pad: float = 8,
) -> float:
    w = stringWidth(text, "Helvetica-Bold", size) + pad * 2
    c.setFillColor(bg)
    c.setStrokeColor(bg)
    c.roundRect(x, y, w, height, height / 2, fill=1, stroke=0)
    c.setFillColor(fg)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(x + w / 2, y + (height - size) / 2 + 1.1, text)
    return w


def label(c: canvas.Canvas, text: str, x: float, y: float, color: Color = BLUE) -> None:
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 7.3)
    c.drawString(x, y, text.upper())


def arrow(
    c: canvas.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    color: Color = BLUE,
    width: float = 1.6,
    head: float = 5,
    dashed: bool = False,
) -> None:
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(width)
    if dashed:
        c.setDash(4, 3)
    c.line(x1, y1, x2, y2)
    c.setDash()
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    left = angle + math.pi * 0.82
    right = angle - math.pi * 0.82
    path = c.beginPath()
    path.moveTo(x2, y2)
    path.lineTo(x2 + head * math.cos(left), y2 + head * math.sin(left))
    path.lineTo(x2 + head * math.cos(right), y2 + head * math.sin(right))
    path.close()
    c.drawPath(path, fill=1, stroke=0)


def flow_node(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: Color = WHITE,
    stroke: Color = LINE,
    fg: Color = INK,
    size: float = 8,
    subtitle: str | None = None,
) -> None:
    rounded_rect(c, x, y, w, h, fill=fill, stroke=stroke, radius=8)
    if subtitle:
        c.setFillColor(fg)
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(x + w / 2, y + h / 2 + 5, text)
        c.setFillColor(MUTED if fg == INK else fg)
        c.setFont("Helvetica", size - 1.5)
        c.drawCentredString(x + w / 2, y + h / 2 - 8, subtitle)
    else:
        lines = wrap_lines(text, "Helvetica-Bold", size, w - 12)
        yy = y + h / 2 + ((len(lines) - 1) * size * 0.55) - size * 0.35
        c.setFillColor(fg)
        c.setFont("Helvetica-Bold", size)
        for line in lines:
            c.drawCentredString(x + w / 2, yy, line)
            yy -= size * 1.15


def top_header(
    c: canvas.Canvas,
    page_num: int,
    eyebrow: str,
    title: str,
    subtitle: str | None = None,
    *,
    dark: bool = False,
    target: bool = False,
) -> float:
    bg = NAVY if dark else PAPER
    fg = WHITE if dark else INK
    sub = HexColor("#B9C5D9") if dark else MUTED
    c.setFillColor(bg)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(BLUE if not dark else HexColor("#6D96FF"))
    c.circle(43, 567, 9, fill=1, stroke=0)
    c.setFillColor(fg)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(58, 564, "ARGMAX MINI")
    c.setFillColor(sub)
    c.setFont("Helvetica", 7.2)
    c.drawRightString(PAGE_W - 42, 564, "AWS EKS ARCHITECTURE CASE STUDY")
    label(c, eyebrow, 42, 536, HexColor("#78A0FF") if dark else BLUE)
    c.setFillColor(fg)
    title_size = 22.0
    title_width = stringWidth(title, "Helvetica-Bold", title_size)
    max_title_width = PAGE_W - 84
    if title_width > max_title_width:
        title_size = max(16.0, title_size * max_title_width / title_width)
    c.setFont("Helvetica-Bold", title_size)
    c.drawString(42, 507, title)
    if target:
        badge(
            c,
            "TARGET ARCHITECTURE / DESIGNED",
            PAGE_W - 214,
            527,
            bg=HexColor("#233C66") if dark else BLUE_SOFT,
            fg=HexColor("#AAC1FF") if dark else BLUE_DARK,
        )
    y = 486
    if subtitle:
        y = draw_paragraph(c, subtitle, 42, 482, 700, size=8.7, leading=11.5, color=sub)
    return y - 7


def footer(c: canvas.Canvas, page_num: int, *, dark: bool = False) -> None:
    line_color = HexColor("#31405B") if dark else LINE
    text_color = HexColor("#8FA0BB") if dark else FAINT
    c.setStrokeColor(line_color)
    c.setLineWidth(0.6)
    c.line(42, 35, PAGE_W - 42, 35)
    c.setFillColor(text_color)
    c.setFont("Helvetica", 6.8)
    c.drawString(42, 21, "Architecture portfolio | evidence-led target design")
    c.setFont("Helvetica-Bold", 6.8)
    c.drawRightString(PAGE_W - 42, 21, f"PAGE {page_num:02d} / {TOTAL_PAGES}")


def page_cover(c: canvas.Canvas) -> None:
    c.setFillColor(PAPER)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(515, 0, PAGE_W - 515, PAGE_H, fill=1, stroke=0)

    c.setFillColor(BLUE)
    c.circle(48, 555, 10, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(64, 552, "ARGMAX MINI")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.3)
    c.drawString(42, 507, "ARCHITECTURE CASE STUDY / 2026")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 31)
    c.drawString(42, 445, "AWS EKS-based MLOps")
    c.drawString(42, 407, "Platform Architecture")
    c.setFillColor(BLUE)
    c.rect(42, 378, 74, 4, fill=1, stroke=0)

    draw_paragraph(
        c,
        "Designing a resilient ML platform for bursty GPU training, isolated data processing, and always-on inference.",
        42,
        345,
        420,
        font="Helvetica-Bold",
        size=13,
        leading=18,
        color=INK_2,
    )
    draw_paragraph(
        c,
        "A source-grounded case study focused on workload boundaries, elastic capacity, failure containment, durable asynchronous workflows, and platform operability.",
        42,
        283,
        415,
        size=9.5,
        leading=14,
        color=MUTED,
    )
    badge(
        c,
        "TARGET ARCHITECTURE + LIMITED API IMPLEMENTATION",
        42,
        211,
        bg=BLUE_SOFT,
        fg=BLUE_DARK,
        size=7.3,
        height=21,
        pad=10,
    )
    label(c, "ROLE", 42, 178, BLUE)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(42, 159, "System Architecture & Backend Design")
    draw_paragraph(
        c,
        "Designed the target architecture and reliability model; implemented the limited API/data foundation.",
        42,
        140,
        420,
        size=7.5,
        leading=10,
        color=MUTED,
    )
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(42, 111, "DevOps / SRE / Infrastructure Engineering Portfolio")

    # Abstract control-plane / data-plane motif.
    c.setFillColor(HexColor("#6F95FF"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(552, 537, "CONTROL PLANE")
    c.setFillColor(HexColor("#9DAAC0"))
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - 42, 537, "intent / policy / reconciliation")
    nodes = [
        (552, 465, 104, 45, "API", "short request"),
        (678, 465, 121, 45, "Controllers", "durable intent"),
        (552, 387, 104, 45, "RDS", "source of truth"),
        (678, 387, 121, 45, "SQS", "at-least-once"),
    ]
    for x, y, w, h, name, sub in nodes:
        flow_node(
            c,
            name,
            x,
            y,
            w,
            h,
            fill=NAVY_2,
            stroke=HexColor("#344663"),
            fg=WHITE,
            subtitle=sub,
        )
    arrow(c, 656, 487, 678, 487, color=HexColor("#6F95FF"))
    arrow(c, 730, 465, 730, 432, color=HexColor("#6F95FF"))
    arrow(c, 678, 409, 656, 409, color=HexColor("#6F95FF"))
    c.setFillColor(HexColor("#6F95FF"))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(552, 331, "DATA PLANE")
    c.setFillColor(HexColor("#9DAAC0"))
    c.setFont("Helvetica", 7)
    c.drawRightString(PAGE_W - 42, 331, "isolated execution / elastic compute")
    flow_node(c, "Processing Job", 552, 253, 113, 47, fill=HexColor("#1C2E4D"), stroke=HexColor("#44628F"), fg=WHITE, subtitle="CPU / memory")
    flow_node(c, "Training Job", 686, 253, 113, 47, fill=HexColor("#1C2E4D"), stroke=HexColor("#44628F"), fg=WHITE, subtitle="dynamic GPU")
    flow_node(c, "KServe", 619, 171, 113, 47, fill=HexColor("#1C2E4D"), stroke=HexColor("#44628F"), fg=WHITE, subtitle="always-on CPU")
    arrow(c, 609, 253, 658, 218, color=HexColor("#6F95FF"), dashed=True)
    arrow(c, 742, 253, 704, 218, color=HexColor("#6F95FF"), dashed=True)
    c.setFillColor(HexColor("#91A0B8"))
    c.setFont("Helvetica", 7)
    c.drawString(552, 116, "AWS EKS target architecture")
    c.drawString(552, 101, "Designed, not represented as production operation")
    c.setStrokeColor(HexColor("#31405B"))
    c.line(552, 81, 799, 81)
    c.setFillColor(HexColor("#91A0B8"))
    c.setFont("Helvetica", 6.8)
    c.drawString(552, 62, "11 pages | selectable text | vector-first diagrams")
    footer(c, 1)
    c.showPage()


def page_workloads(c: canvas.Canvas) -> None:
    top_header(
        c,
        2,
        "01 / WORKLOAD CHARACTERISTICS",
        "One platform, four different operating models",
        "The architecture starts with lifecycle, resource profile, failure domain, and scaling behavior - not with a favorite service.",
    )
    cards = [
        {
            "title": "Backend API",
            "badge": "ALWAYS-ON",
            "color": BLUE,
            "soft": BLUE_SOFT,
            "rows": [
                ("Lifecycle", "short request / response"),
                ("Compute", "CPU | control-plane work"),
                ("Isolation", "API Pod"),
                ("Scaling", "replicated Pods on managed nodes"),
            ],
        },
        {
            "title": "Dataset processing",
            "badge": "K8S JOB",
            "color": CYAN,
            "soft": CYAN_SOFT,
            "rows": [
                ("Lifecycle", "up to 2 GB per version"),
                ("Compute", "CPU / memory intensive"),
                ("Isolation", "one Job per DatasetVersion"),
                ("Scaling", "controller creates Jobs"),
            ],
        },
        {
            "title": "GPU training",
            "badge": "K8S JOB",
            "color": PURPLE,
            "soft": PURPLE_SOFT,
            "rows": [
                ("Lifecycle", "12-24 hour batch"),
                ("Compute", "bursty, scarce GPU"),
                ("Isolation", "one Job per TrainingJob"),
                ("Scaling", "Karpenter GPU capacity"),
            ],
        },
        {
            "title": "Model serving",
            "badge": "ALWAYS-ON",
            "color": GREEN,
            "soft": GREEN_SOFT,
            "rows": [
                ("Lifecycle", "latency-sensitive traffic"),
                ("Compute", "CPU serving for XGBoost"),
                ("Isolation", "KServe InferenceService"),
                ("Scaling", "minimum replicas >= 1"),
            ],
        },
    ]
    x0, gap, w, y0, h = 42, 12, 180, 143, 311
    for idx, item in enumerate(cards):
        x = x0 + idx * (w + gap)
        rounded_rect(c, x, y0, w, h, fill=WHITE, stroke=LINE, radius=12)
        c.setFillColor(item["color"])
        c.roundRect(x, y0 + h - 5, w, 5, 3, fill=1, stroke=0)
        badge(c, item["badge"], x + 14, y0 + h - 42, bg=item["soft"], fg=item["color"], size=6.7, height=17, pad=7)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(x + 14, y0 + h - 69, item["title"])
        yy = y0 + h - 99
        for row_label, value in item["rows"]:
            c.setFillColor(item["color"])
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(x + 14, yy, row_label.upper())
            yy = draw_paragraph(c, value, x + 14, yy - 15, w - 28, font="Helvetica-Bold", size=8.3, leading=10.7, color=INK)
            yy -= 10
            if row_label != "Scaling":
                c.setStrokeColor(HexColor("#ECEDE9"))
                c.line(x + 14, yy + 4, x + w - 14, yy + 4)
                yy -= 5
    rounded_rect(c, 42, 63, PAGE_W - 84, 57, fill=INK, stroke=INK, radius=10)
    c.setFillColor(HexColor("#7EA4FF"))
    c.setFont("Helvetica-Bold", 7)
    c.drawString(59, 98, "ARCHITECTURE CONSEQUENCE")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(59, 79, "Separate execution boundaries keep a 2 GB parse or a 24-hour GPU run out of the API request path.")
    footer(c, 2)
    c.showPage()


def page_architecture(c: canvas.Canvas) -> None:
    top_header(
        c,
        3,
        "02 / CONTROL PLANE + DATA PLANE",
        "Durable intent in PostgreSQL; isolated execution in Kubernetes",
        "Simplified vector redraw of the repository system architecture diagram. Managed AWS services remain outside the EKS execution boundary.",
        target=True,
    )
    # Left edge.
    flow_node(c, "Users / CI", 42, 281, 77, 52, fill=WHITE, stroke=LINE, subtitle="external entry")
    flow_node(c, "Route 53", 142, 383, 78, 42, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE_DARK)
    flow_node(c, "WAF", 142, 317, 78, 42, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE_DARK)
    flow_node(c, "ALB", 142, 251, 78, 42, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE_DARK)
    arrow(c, 119, 307, 142, 404)
    arrow(c, 181, 383, 181, 359)
    arrow(c, 181, 317, 181, 293)

    # EKS boundary.
    eks_x, eks_y, eks_w, eks_h = 245, 102, 391, 350
    rounded_rect(c, eks_x, eks_y, eks_w, eks_h, fill=WHITE, stroke=BLUE, radius=13, line_width=1.3)
    badge(c, "AMAZON EKS", eks_x + 14, eks_y + eks_h - 30, bg=BLUE, fg=WHITE, size=7, height=18, pad=9)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawRightString(eks_x + eks_w - 14, eks_y + eks_h - 24, "workload and policy boundary")
    rounded_rect(c, eks_x + 14, eks_y + 190, eks_w - 28, 117, fill=BLUE_SOFT, stroke=HexColor("#B9C9F4"), radius=9)
    label(c, "CONTROL PLANE WORKLOADS", eks_x + 27, eks_y + 286, BLUE_DARK)
    cp = [
        ("Backend API", "intent"),
        ("Dataset Ctrl", "Jobs"),
        ("Training Ctrl", "Jobs"),
        ("Deploy Ctrl", "KServe"),
        ("Inference GW", "routing"),
    ]
    for i, (name, sub) in enumerate(cp):
        xx = eks_x + 26 + i * 68.5
        flow_node(c, name, xx, eks_y + 211, 59, 49, fill=WHITE, stroke=HexColor("#B9C9F4"), fg=INK, size=6.7, subtitle=sub)

    rounded_rect(c, eks_x + 14, eks_y + 31, eks_w - 28, 140, fill=HexColor("#F7F8FA"), stroke=LINE, radius=9)
    label(c, "DATA PLANE WORKLOADS", eks_x + 27, eks_y + 150, PURPLE)
    flow_node(c, "Processing Jobs", eks_x + 27, eks_y + 76, 99, 52, fill=CYAN_SOFT, stroke=CYAN, fg=CYAN, subtitle="CPU / memory")
    flow_node(c, "Training Jobs", eks_x + 145, eks_y + 76, 99, 52, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE, subtitle="dynamic GPU")
    flow_node(c, "KServe", eks_x + 263, eks_y + 76, 87, 52, fill=GREEN_SOFT, stroke=GREEN, fg=GREEN, subtitle="always-on CPU")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.5)
    c.drawString(eks_x + 27, eks_y + 51, "Platform services: MLflow | Prometheus / Grafana | Karpenter | External Secrets")

    arrow(c, 220, 272, eks_x, 272)

    # AWS managed services.
    svc_x = 663
    services = [
        ("RDS PostgreSQL", "business state", BLUE_SOFT, BLUE),
        ("Amazon SQS", "wake-up signal", AMBER_SOFT, AMBER),
        ("Amazon S3", "artifacts / data", GREEN_SOFT, GREEN),
        ("CloudWatch", "logs + AWS metrics", CYAN_SOFT, CYAN),
        ("Glue / Athena", "analytics", PURPLE_SOFT, PURPLE),
    ]
    sy = 386
    for name, sub, soft, col in services:
        flow_node(c, name, svc_x, sy, 136, 45, fill=soft, stroke=col, fg=col, subtitle=sub)
        sy -= 60
    arrow(c, eks_x + eks_w, 388, svc_x, 408, color=BLUE)
    arrow(c, eks_x + eks_w, 337, svc_x, 348, color=AMBER)
    arrow(c, eks_x + eks_w, 217, svc_x, 288, color=GREEN)
    arrow(c, eks_x + eks_w, 167, svc_x, 228, color=CYAN, dashed=True)
    arrow(c, svc_x, 168, eks_x + eks_w, 138, color=PURPLE, dashed=True)

    # Principle strip.
    principles = [
        ("RDS", "source of truth", BLUE),
        ("SQS", "at-least-once signal", AMBER),
        ("K8s API", "execution observation", PURPLE),
        ("S3", "large-object path", GREEN),
    ]
    for i, (name, text, col) in enumerate(principles):
        x = 42 + i * 192
        c.setFillColor(col)
        c.circle(x + 3, 70, 3, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 7.3)
        c.drawString(x + 12, 72, name)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.1)
        c.drawString(x + 12, 59, text)
    footer(c, 3)
    c.showPage()


def page_capacity(c: canvas.Canvas) -> None:
    top_header(
        c,
        4,
        "03 / KUBERNETES CAPACITY",
        "Keep the platform warm; make expensive GPU capacity elastic",
        "Karpenter is scoped to GPU training. Core services stay on a managed node group, and GPU nodes may scale to zero when no training Pod is pending.",
        target=True,
    )
    # Capacity lanes.
    rounded_rect(c, 42, 305, 361, 143, fill=WHITE, stroke=BLUE, radius=12)
    badge(c, "MANAGED NODE GROUP", 58, 416, bg=BLUE_SOFT, fg=BLUE_DARK)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(58, 387, "Always-on platform baseline")
    draw_bullets(
        c,
        [
            "Backend API, controllers, Inference Gateway and KServe baseline",
            "MLflow, observability, Karpenter Controller, CoreDNS and cluster services",
            "Stable capacity for latency-sensitive and control-plane workloads",
        ],
        58,
        361,
        324,
        size=7.7,
        leading=9.7,
        gap=4,
        dot_color=BLUE,
    )
    rounded_rect(c, 438, 305, 361, 143, fill=NAVY, stroke=NAVY, radius=12)
    badge(c, "KARPENTER GPU NODEPOOL", 454, 416, bg=HexColor("#283E63"), fg=HexColor("#AFC5FF"))
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(454, 387, "Burst capacity for training only")
    draw_bullets(
        c,
        [
            "Provisioned by a pending Pod requesting nvidia.com/gpu",
            "GPU labels, taints, tolerations and affinity prevent accidental placement",
            "NodePool limits cap capacity; On-Demand is the default capacity type",
        ],
        454,
        361,
        324,
        size=7.7,
        leading=9.7,
        color=WHITE,
        dot_color=HexColor("#7EA4FF"),
        gap=4,
    )

    # Provisioning flow.
    label(c, "ELASTIC GPU PROVISIONING LOOP", 42, 273, PURPLE)
    steps = [
        ("SQS event", "wake-up"),
        ("Training Ctrl", "creates Job"),
        ("Pending Pod", "requests GPU"),
        ("Karpenter", "selects capacity"),
        ("GPU node", "On-Demand"),
        ("Training Job", "checkpoint to S3"),
    ]
    x, y, w, h, gap = 42, 184, 110, 57, 20
    for i, (name, sub) in enumerate(steps):
        col = PURPLE if i in (2, 3, 4, 5) else BLUE
        soft = PURPLE_SOFT if col == PURPLE else BLUE_SOFT
        flow_node(c, name, x + i * (w + gap), y, w, h, fill=soft, stroke=col, fg=col, subtitle=sub)
        if i < len(steps) - 1:
            arrow(c, x + i * (w + gap) + w, y + h / 2, x + (i + 1) * (w + gap) - 5, y + h / 2, color=col)
    rounded_rect(c, 42, 66, 757, 84, fill=WHITE, stroke=LINE, radius=10)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9.3)
    c.drawString(58, 124, "Cost controls bound elastic capacity (target design)")
    guards = [
        "GPU nodes scale to zero when idle",
        "NodePool limit caps aggregate GPUs",
        "On-Demand is the reliability baseline",
        "Spot only after checkpoint / retry validation",
        "Consolidate empty nodes; protect long jobs",
        "KServe Standard accepts warm-serving cost",
    ]
    yy = 100
    for i, item in enumerate(guards):
        xx = 58 + (i % 3) * 246
        row_y = yy - (i // 3) * 23
        c.setFillColor(PURPLE)
        c.circle(xx + 2, row_y + 2, 2, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.3)
        c.drawString(xx + 9, row_y, item)
    footer(c, 4)
    c.showPage()


def page_failure(c: canvas.Canvas) -> None:
    top_header(
        c,
        5,
        "04 / FAILURE ISOLATION",
        "Design the blast radius before designing the happy path",
        "Large uploads and long-running training are execution workflows, not API request handlers. Each unit of work gets its own failure boundary.",
        target=True,
    )
    # Anti-pattern.
    rounded_rect(c, 42, 275, 277, 174, fill=RED_SOFT, stroke=HexColor("#E4B5AF"), radius=12)
    badge(c, "AVOID", 58, 416, bg=HexColor("#F1CBC6"), fg=RED)
    c.setFillColor(RED)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(58, 387, "One synchronous request path")
    flow_node(c, "API Pod", 61, 318, 82, 43, fill=WHITE, stroke=RED, fg=RED)
    flow_node(c, "2 GB parse", 166, 344, 122, 40, fill=WHITE, stroke=RED, fg=RED)
    flow_node(c, "12-24h training", 166, 294, 122, 40, fill=WHITE, stroke=RED, fg=RED)
    arrow(c, 143, 339, 166, 364, color=RED)
    arrow(c, 143, 339, 166, 314, color=RED)
    c.setFillColor(RED)
    c.setFont("Helvetica", 7.4)
    c.drawString(58, 290, "OOM, timeout, and deploy coupling share one blast radius.")

    # Designed pattern.
    rounded_rect(c, 343, 275, 456, 174, fill=GREEN_SOFT, stroke=HexColor("#A9D0BF"), radius=12)
    badge(c, "DESIGNED", 359, 416, bg=HexColor("#CDE6DB"), fg=GREEN)
    c.setFillColor(GREEN)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(359, 387, "Intent in API; execution in isolated workloads")
    flow_node(c, "Backend API", 359, 322, 91, 48, fill=WHITE, stroke=GREEN, fg=GREEN, subtitle="validate + persist")
    flow_node(c, "RDS + Outbox", 474, 322, 97, 48, fill=WHITE, stroke=GREEN, fg=GREEN, subtitle="durable intent")
    flow_node(c, "Processing Job", 597, 365, 94, 44, fill=WHITE, stroke=CYAN, fg=CYAN)
    flow_node(c, "Training Job", 597, 311, 94, 44, fill=WHITE, stroke=PURPLE, fg=PURPLE)
    flow_node(c, "KServe", 705, 338, 78, 44, fill=WHITE, stroke=BLUE, fg=BLUE)
    arrow(c, 450, 346, 474, 346, color=GREEN)
    arrow(c, 571, 346, 597, 387, color=CYAN)
    arrow(c, 571, 346, 597, 333, color=PURPLE)
    arrow(c, 691, 333, 705, 360, color=BLUE, dashed=True)
    c.setFillColor(GREEN)
    c.setFont("Helvetica", 7.4)
    c.drawString(359, 290, "Each resource is observable, retryable, and replaceable on its own boundary.")

    label(c, "FAILURE DOMAIN MATRIX", 42, 244, BLUE)
    failures = [
        ("Processing runtime failure", "one DatasetVersion Job", "retry only if classified retryable", CYAN),
        ("GPU / node loss", "one TrainingJob", "checkpoint + retry", PURPLE),
        ("Duplicate SQS", "one event delivery", "idempotency + conditional update", AMBER),
        ("API rollout", "API Deployment", "training continues independently", BLUE),
    ]
    for i, (failure, radius, response, col) in enumerate(failures):
        xx = 42 + i * 192
        rounded_rect(c, xx, 82, 180, 137, fill=WHITE, stroke=LINE, radius=10)
        c.setFillColor(col)
        c.rect(xx, 208, 180, 11, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(xx + 13, 185, failure)
        label(c, "BLAST RADIUS", xx + 13, 160, col)
        draw_paragraph(c, radius, xx + 13, 145, 154, font="Helvetica-Bold", size=7.5, leading=9.5, color=INK)
        label(c, "RECOVERY MECHANISM", xx + 13, 115, col)
        draw_paragraph(c, response, xx + 13, 100, 154, size=7.2, leading=9.2, color=MUTED)
    footer(c, 5)
    c.showPage()


def page_reliability(c: canvas.Canvas) -> None:
    top_header(
        c,
        6,
        "05 / RELIABILITY MECHANICS",
        "Separate the queue handoff from the 12-24 hour training lifecycle",
        "SQS wakes the controller; it is not the job store. PostgreSQL owns business intent, while Kubernetes reports execution state and S3 holds checkpoints.",
        target=True,
    )
    # Sequence strip - the queue owns only the handoff window.
    rounded_rect(c, 42, 349, 757, 99, fill=WHITE, stroke=LINE, radius=12)
    badge(c, "SQS HANDOFF VS LONG-RUNNING EXECUTION", 56, 421, bg=AMBER_SOFT, fg=AMBER, size=6.5, height=18)
    steps = [
        ("API + RDS", "QUEUED + outbox", BLUE, BLUE_SOFT),
        ("Outbox -> SQS", "wake-up only", AMBER, AMBER_SOFT),
        ("Training Ctrl", "re-read + CAS", GREEN, GREEN_SOFT),
        ("Kubernetes API", "create / verify Job", PURPLE, PURPLE_SOFT),
        ("GPU Job + S3", "12-24h + checkpoint", PURPLE, PURPLE_SOFT),
    ]
    sx, sy, sw, sh, sg = 56, 371, 127, 38, 19
    for i, (name, sub, col, soft) in enumerate(steps):
        flow_node(c, name, sx + i * (sw + sg), sy, sw, sh, fill=soft, stroke=col, fg=col, subtitle=sub, size=7.0)
        if i < len(steps) - 1:
            arrow(c, sx + i * (sw + sg) + sw, sy + sh / 2, sx + (i + 1) * (sw + sg) - 4, sy + sh / 2, color=col)
    c.setFillColor(AMBER)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(56, 358, "QUEUE HANDOFF / RETRY WINDOW")
    c.setFillColor(PURPLE)
    c.drawString(641, 358, "EXECUTION LIFECYCLE")

    # Column 1 - transactional outbox and cleanup policy.
    y1, h = 142, 185
    x1, w1 = 42, 235
    rounded_rect(c, x1, y1, w1, h, fill=WHITE, stroke=LINE, radius=12)
    badge(c, "1 / OUTBOX + RETENTION", x1 + 14, y1 + h - 34, bg=BLUE_SOFT, fg=BLUE_DARK, size=6.5)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(x1 + 14, y1 + h - 60, "Intent and event commit together")
    flow_node(c, "Business row", x1 + 14, y1 + 81, 90, 42, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE, subtitle="PostgreSQL", size=7.1)
    flow_node(c, "OutboxEvent", x1 + 130, y1 + 81, 90, 42, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE, subtitle="same transaction", size=7.1)
    arrow(c, x1 + 104, y1 + 102, x1 + 130, y1 + 102, color=BLUE)
    draw_bullets(
        c,
        [
            "Published rows: retain 30 days, then cleanup job",
            "Unpublished rows: never auto-delete",
            "Retry with backoff; duplicate delivery remains possible",
        ],
        x1 + 15,
        y1 + 61,
        w1 - 30,
        size=6.8,
        leading=8.6,
        gap=3.2,
        dot_color=BLUE,
    )

    # Column 2 - TrainingJob state machine.
    x2, w2 = 292, 266
    rounded_rect(c, x2, y1, w2, h, fill=NAVY, stroke=NAVY, radius=12)
    badge(c, "2 / TRAININGJOB STATE", x2 + 14, y1 + h - 34, bg=HexColor("#283E63"), fg=HexColor("#AFC5FF"), size=6.5)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(x2 + 14, y1 + h - 60, "Advance only from a valid predecessor")
    states = [("QUEUED", BLUE), ("SCHEDULING", PURPLE), ("RUNNING", AMBER), ("SUCCEEDED", GREEN)]
    nx, ny, nw, nh, ng = x2 + 14, y1 + 88, 53, 37, 9
    for i, (name, col) in enumerate(states):
        flow_node(c, name, nx + i * (nw + ng), ny, nw, nh, fill=HexColor("#17243A"), stroke=col, fg=WHITE, size=5.7)
        if i < len(states) - 1:
            arrow(c, nx + i * (nw + ng) + nw, ny + nh / 2, nx + (i + 1) * (nw + ng) - 3, ny + nh / 2, color=HexColor("#7EA4FF"))
    rounded_rect(c, x2 + 14, y1 + 20, w2 - 28, 53, fill=HexColor("#17243A"), stroke=HexColor("#405170"), radius=7)
    c.setFillColor(HexColor("#AFC5FF"))
    c.setFont("Helvetica-Bold", 6.1)
    c.drawString(x2 + 23, y1 + 58, "FAILURE")
    c.setFillColor(WHITE)
    c.setFont("Helvetica", 6.3)
    c.drawString(x2 + 68, y1 + 58, "active state -> FAILED")
    c.setFillColor(HexColor("#F2CE79"))
    c.setFont("Helvetica-Bold", 6.1)
    c.drawString(x2 + 23, y1 + 40, "CANCEL RACE")
    c.setFillColor(WHITE)
    c.setFont("Helvetica", 6.1)
    c.drawString(x2 + 83, y1 + 40, "CANCEL_REQUESTED -> CANCELLED / SUCCEEDED / FAILED")
    c.setFillColor(HexColor("#AEB9CA"))
    c.setFont("Helvetica", 5.9)
    c.drawString(x2 + 23, y1 + 25, "Terminal observation decides the final business state.")

    # Column 3 - reconciliation is a repair path, not a latency SLO.
    x3, w3 = 573, 226
    rounded_rect(c, x3, y1, w3, h, fill=WHITE, stroke=LINE, radius=12)
    badge(c, "3 / 60s RECONCILER", x3 + 14, y1 + h - 34, bg=GREEN_SOFT, fg=GREEN, size=6.5)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10.2)
    c.drawString(x3 + 14, y1 + h - 60, "Repair and converge")
    flow_node(c, "RDS intent", x3 + 14, y1 + 83, 78, 42, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE, size=6.8)
    flow_node(c, "Controller", x3 + 119, y1 + 83, 91, 42, fill=GREEN_SOFT, stroke=GREEN, fg=GREEN, size=6.8)
    arrow(c, x3 + 92, y1 + 104, x3 + 119, y1 + 104, color=GREEN)
    flow_node(c, "Kubernetes observation", x3 + 55, y1 + 36, 128, 34, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE, size=6.2)
    arrow(c, x3 + 164, y1 + 83, x3 + 136, y1 + 70, color=PURPLE)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.2)
    c.drawString(x3 + 14, y1 + 22, "Not an event-latency or user-facing SLO.")
    c.setFont("Helvetica-Bold", 5.8)
    c.drawString(x3 + 14, y1 + 9, "Shorter = more polling  |  Longer = more recovery lag")

    # CAS guardrail remains explicit.
    rounded_rect(c, 42, 65, 757, 54, fill=HexColor("#0B1220"), stroke=HexColor("#31405B"), radius=9)
    badge(c, "CONDITIONAL TRANSITION", 55, 88, bg=HexColor("#283E63"), fg=HexColor("#AFC5FF"), size=6.1, height=18)
    c.setFillColor(HexColor("#D8E4FF"))
    c.setFont("Courier-Bold", 6.8)
    c.drawString(198, 94, "UPDATE training_jobs SET status='RUNNING' WHERE id=:id AND status='SCHEDULING';")
    c.setFillColor(HexColor("#8BD5B5"))
    c.setFont("Helvetica-Bold", 6.4)
    c.drawString(198, 78, "Only rows_affected = 1 advances; deterministic Job names absorb duplicate effects.")
    footer(c, 6)
    c.showPage()


def page_observability(c: canvas.Canvas) -> None:
    top_header(
        c,
        7,
        "06 / OBSERVABILITY",
        "Correlate user intent, controller decisions, Kubernetes execution, and AWS signals",
        "Metrics, logs, and identifiers are designed around a distributed workflow. UUIDs belong in structured logs, not high-cardinality Prometheus labels.",
        target=True,
    )
    cols = [
        (42, 239, "PROMETHEUS STACK", BLUE, BLUE_SOFT),
        (301, 239, "STRUCTURED LOG PIPELINE", GREEN, GREEN_SOFT),
        (560, 239, "AWS SERVICE SIGNALS", PURPLE, PURPLE_SOFT),
    ]
    for x, w, title, col, soft in cols:
        rounded_rect(c, x, 169, w, 279, fill=WHITE, stroke=LINE, radius=12)
        badge(c, title, x + 14, 417, bg=soft, fg=col, size=6.5, height=18, pad=8)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(56, 384, "Platform and workload metrics")
    draw_bullets(
        c,
        [
            "Backend API and controllers",
            "Processing / Training Jobs and KServe",
            "Karpenter and Kubernetes Nodes",
            "kube-state-metrics + node-exporter",
            "NVIDIA DCGM Exporter for GPU signals",
        ],
        56,
        357,
        210,
        size=7.6,
        leading=9.5,
        gap=5,
        dot_color=BLUE,
    )
    flow_node(c, "Prometheus", 58, 205, 83, 44, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE)
    flow_node(c, "Grafana", 154, 205, 71, 44, fill=BLUE_SOFT, stroke=BLUE, fg=BLUE)
    arrow(c, 141, 227, 154, 227, color=BLUE)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(58, 186, "Alertmanager routes actionable platform alerts.")

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(315, 384, "One path from Pod to search")
    log_steps = [
        ("App / Job / Ctrl", "stdout / stderr"),
        ("Fluent Bit", "collection"),
        ("CloudWatch Logs", "central search"),
    ]
    yy = 325
    for i, (name, sub) in enumerate(log_steps):
        flow_node(c, name, 327, yy, 187, 45, fill=GREEN_SOFT if i != 2 else CYAN_SOFT, stroke=GREEN if i != 2 else CYAN, fg=GREEN if i != 2 else CYAN, subtitle=sub)
        if i < len(log_steps) - 1:
            arrow(c, 420, yy, 420, yy - 18, color=GREEN)
        yy -= 69
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(315, 186, "Includes KServe access logs and controller decisions.")

    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(574, 384, "CloudWatch service context")
    aws = ["ALB", "RDS", "SQS", "S3", "EKS control plane"]
    for i, name in enumerate(aws):
        xx = 574 + (i % 2) * 104
        yy = 334 - (i // 2) * 57
        flow_node(c, name, xx, yy, 91, 38, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE, size=7.4)
    rounded_rect(c, 574, 198, 193, 48, fill=AMBER_SOFT, stroke=AMBER, radius=8)
    c.setFillColor(AMBER)
    c.setFont("Helvetica-Bold", 7.3)
    c.drawString(587, 226, "NO INVENTED SLO THRESHOLDS")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 6.8)
    c.drawString(587, 210, "Signals are defined; targets require real baselines.")

    rounded_rect(c, 42, 66, 757, 78, fill=NAVY, stroke=NAVY, radius=10)
    c.setFillColor(HexColor("#83A8FF"))
    c.setFont("Helvetica-Bold", 7)
    c.drawString(58, 120, "CORRELATION CONTRACT")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 8.4)
    c.drawString(58, 99, "Synchronous")
    c.setFillColor(HexColor("#C4CEDD"))
    c.setFont("Helvetica", 7.4)
    c.drawString(125, 99, "request_id")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 8.4)
    c.drawString(215, 99, "Asynchronous")
    c.setFillColor(HexColor("#C4CEDD"))
    c.setFont("Helvetica", 7.4)
    c.drawString(300, 99, "event_id + resource_id")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 8.4)
    c.drawString(465, 99, "Structured fields")
    c.setFillColor(HexColor("#C4CEDD"))
    c.setFont("Helvetica", 7.1)
    c.drawString(562, 99, "service | user_id | training_job_id | error_code")
    c.setFillColor(HexColor("#8FA0BB"))
    c.setFont("Helvetica", 6.7)
    c.drawString(58, 79, "Identifiers live in logs for traceability; bounded dimensions live in metrics for operational aggregation.")
    footer(c, 7)
    c.showPage()


def page_security(c: canvas.Canvas) -> None:
    top_header(
        c,
        8,
        "07 / SECURITY",
        "Identity and trust boundaries follow the workload, not the node",
        "External traffic is filtered before EKS, AWS access uses workload identity, and secrets are synchronized without long-lived access keys in Pods.",
        target=True,
    )
    # Request and trust boundary.
    label(c, "EXTERNAL REQUEST PATH", 42, 448, BLUE)
    req = [
        ("Internet", "client"),
        ("Route 53", "DNS"),
        ("AWS WAF", "edge policy"),
        ("ALB", "TLS ingress"),
        ("EKS workload", "API / gateway"),
    ]
    x, y, w, gap = 42, 371, 125, 27
    for i, (name, sub) in enumerate(req):
        flow_node(c, name, x + i * (w + gap), y, w, 51, fill=BLUE_SOFT if i < 4 else NAVY, stroke=BLUE if i < 4 else NAVY, fg=BLUE_DARK if i < 4 else WHITE, subtitle=sub)
        if i < len(req) - 1:
            arrow(c, x + i * (w + gap) + w, y + 25, x + (i + 1) * (w + gap) - 5, y + 25, color=BLUE)

    # Identity and secret flows.
    rounded_rect(c, 42, 188, 367, 153, fill=WHITE, stroke=LINE, radius=12)
    badge(c, "AWS WORKLOAD IDENTITY", 58, 309, bg=GREEN_SOFT, fg=GREEN)
    flow_node(c, "ServiceAccount", 59, 235, 93, 48, fill=GREEN_SOFT, stroke=GREEN, fg=GREEN, subtitle="per workload")
    flow_node(c, "IRSA role", 179, 235, 84, 48, fill=GREEN_SOFT, stroke=GREEN, fg=GREEN, subtitle="least privilege")
    flow_node(c, "S3 / SQS", 290, 235, 93, 48, fill=GREEN_SOFT, stroke=GREEN, fg=GREEN, subtitle="scoped access")
    arrow(c, 152, 259, 179, 259, color=GREEN)
    arrow(c, 263, 259, 290, 259, color=GREEN)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(59, 211, "Pods do not store long-lived AWS access keys.")

    rounded_rect(c, 432, 188, 367, 153, fill=WHITE, stroke=LINE, radius=12)
    badge(c, "SECRET DELIVERY", 448, 309, bg=PURPLE_SOFT, fg=PURPLE)
    flow_node(c, "Secrets Manager", 449, 235, 101, 48, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE, subtitle="encrypted source")
    flow_node(c, "External Secrets", 576, 235, 96, 48, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE, subtitle="operator")
    flow_node(c, "K8s Secret -> Pod", 698, 235, 84, 48, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE, subtitle="runtime mount")
    arrow(c, 550, 259, 576, 259, color=PURPLE)
    arrow(c, 672, 259, 698, 259, color=PURPLE)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(449, 211, "Only the operator reads Secrets Manager directly.")

    label(c, "DEFENSE-IN-DEPTH CONTROLS", 42, 159, AMBER)
    controls = [
        ("Network", "Security Groups + VPC CNI NetworkPolicy; default-deny namespaces"),
        ("Pod", "non-root | no privilege escalation | drop all capabilities | RuntimeDefault seccomp"),
        ("Encryption", "external TLS | S3 SSE-KMS | RDS / SQS / EBS encryption at rest"),
        ("Private", "RDS is not public; KServe and MLflow remain cluster-private"),
    ]
    for i, (name, text) in enumerate(controls):
        xx = 42 + i * 192
        rounded_rect(c, xx, 65, 180, 72, fill=AMBER_SOFT, stroke=HexColor("#DEC98D"), radius=9)
        c.setFillColor(AMBER)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(xx + 12, 115, name.upper())
        draw_paragraph(c, text, xx + 12, 98, 156, size=6.6, leading=8.4, color=INK)
    footer(c, 8)
    c.showPage()


def page_gitops(c: canvas.Canvas) -> None:
    top_header(
        c,
        9,
        "08 / CI/CD + GITOPS",
        "A Git contract turns deployment into a reconciled platform capability",
        "Target Architecture - Designed, Not Deployed. Developers change code and declared configuration; the delivery system converges the cluster.",
        dark=True,
        target=True,
    )
    c.setFillColor(HexColor("#D9E3F2"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(42, 447, "DESIGNED DELIVERY FLOW")
    steps = [
        ("GitHub", "source + config"),
        ("GitHub Actions", "test / lint / scan"),
        ("Amazon ECR", "immutable image"),
        ("Helm values", "desired version"),
        ("Argo CD", "reconcile"),
        ("Amazon EKS", "running state"),
    ]
    x, y, w, gap = 42, 348, 112, 18
    for i, (name, sub) in enumerate(steps):
        active = i in (1, 4)
        fill = HexColor("#263B60") if active else NAVY_2
        stroke = HexColor("#6E97FF") if active else HexColor("#384A66")
        flow_node(c, name, x + i * (w + gap), y, w, 62, fill=fill, stroke=stroke, fg=WHITE, subtitle=sub)
        if i < len(steps) - 1:
            arrow(c, x + i * (w + gap) + w, y + 31, x + (i + 1) * (w + gap) - 4, y + 31, color=HexColor("#6E97FF"))
    c.setFillColor(HexColor("#8FA0BB"))
    c.setFont("Helvetica", 6.8)
    c.drawString(42, 329, "CI validates and produces an artifact. Git records desired deployment state. Argo CD owns cluster convergence.")

    rounded_rect(c, 42, 166, 361, 128, fill=NAVY_2, stroke=HexColor("#344663"), radius=11)
    badge(c, "CONTINUOUS INTEGRATION", 58, 260, bg=HexColor("#283E63"), fg=HexColor("#AFC5FF"), size=6.6)
    draw_bullets(
        c,
        [
            "run tests and lint checks",
            "build container image and vulnerability scan",
            "push immutable artifact to Amazon ECR",
            "update declared image tag / Helm values",
        ],
        58,
        236,
        328,
        size=7.4,
        leading=9.2,
        color=WHITE,
        dot_color=HexColor("#7EA4FF"),
        gap=3,
    )
    rounded_rect(c, 438, 166, 361, 128, fill=NAVY_2, stroke=HexColor("#344663"), radius=11)
    badge(c, "CONTINUOUS DELIVERY", 454, 260, bg=HexColor("#24473E"), fg=HexColor("#A4E3CC"), size=6.6)
    draw_bullets(
        c,
        [
            "Argo CD watches the declared Git state",
            "Helm renders repeatable Kubernetes resources",
            "drift is detected and reconciled through one control loop",
            "cluster changes remain auditable through the Git history",
        ],
        454,
        236,
        328,
        size=7.4,
        leading=9.2,
        color=WHITE,
        dot_color=HexColor("#74D1AF"),
        gap=3,
    )
    rounded_rect(c, 42, 66, 757, 72, fill=HexColor("#162B4B"), stroke=HexColor("#36527C"), radius=10)
    c.setFillColor(HexColor("#7EA4FF"))
    c.setFont("Helvetica-Bold", 7)
    c.drawString(58, 115, "DEVELOPER PLATFORM ANGLE")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 9.3)
    c.drawString(58, 93, "Developers interact with a reviewed Git contract - not ad hoc cluster operations.")
    c.setFillColor(HexColor("#9DACC1"))
    c.setFont("Helvetica", 6.9)
    c.drawString(58, 77, "Terraform is intentionally outside this documented delivery scope.")
    footer(c, 9, dark=True)
    c.showPage()


def tradeoff_row(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    name: str,
    decision: str,
    effect: str,
    color: Color,
    soft: Color,
) -> None:
    rounded_rect(c, x, y, w, 64, fill=WHITE, stroke=LINE, radius=8)
    c.setFillColor(soft)
    c.rect(x, y, 7, 64, fill=1, stroke=0)
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(x + 17, y + 44, name)
    draw_paragraph(c, decision, x + 17, y + 29, w - 34, size=6.8, leading=8.1, color=INK, max_lines=2)
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(x + 17, y + 10, effect.upper())


def page_tradeoffs(c: canvas.Canvas) -> None:
    top_header(
        c,
        10,
        "09 / TRADE-OFFS",
        "Add complexity only when the workload pays for it",
        "The platform accepts operational costs where they buy isolation, durability, or elastic scarce capacity - and postpones components without a demonstrated requirement.",
        target=True,
    )
    badge(c, "ADOPTED IN THE TARGET DESIGN", 42, 437, bg=GREEN_SOFT, fg=GREEN, size=6.9)
    badge(c, "NOT ADOPTED INITIALLY", 438, 437, bg=AMBER_SOFT, fg=AMBER, size=6.9)
    adopted = [
        ("Amazon EKS", "One scheduler and policy model for Jobs, GPU, and KServe.", "cost: cluster operations"),
        ("SQS + Outbox", "Durable async intent without coupling work to an API request.", "cost: idempotency + publisher"),
        ("Karpenter", "Elastic GPU nodes for bursty 12-24h training workloads.", "cost: scheduling latency"),
        ("PostgreSQL", "Constraints and transactions provide the source of truth.", "cost: reconciliation duty"),
        ("KServe Standard", "Standard cluster-local serving without a Knative dependency.", "effect: min replicas >= 1"),
    ]
    deferred = [
        ("Redis", "No demonstrated metadata bottleneck beyond PostgreSQL.", "revisit with evidence"),
        ("KEDA", "The controller already consumes SQS and creates Kubernetes Jobs.", "avoid duplicate control loop"),
        ("Knative", "No scale-to-zero or event-streaming requirement for initial serving.", "keep serving simpler"),
        ("Envoy Gateway", "ALB + Inference Gateway + ClusterIP cover documented routing.", "avoid another gateway"),
        ("CloudFront", "No static distribution or download-acceleration requirement.", "add only if workload changes"),
    ]
    y = 355
    for i, row in enumerate(adopted):
        tradeoff_row(c, 42, y - i * 70, 361, *row, GREEN, GREEN_SOFT)
    for i, row in enumerate(deferred):
        tradeoff_row(c, 438, y - i * 70, 361, *row, AMBER, AMBER_SOFT)
    footer(c, 10)
    c.showPage()


def page_evidence(c: canvas.Canvas, portfolio_url: str, repo_url: str) -> None:
    top_header(
        c,
        11,
        "10 / EVIDENCE + PORTFOLIO LINKS",
        "Designed architecture, implemented foundations, explicit boundary",
        "The case study shows system-level reasoning without representing the AWS target architecture as already deployed or operated in production.",
    )
    # Designed vs implemented.
    rounded_rect(c, 42, 255, 361, 195, fill=BLUE_SOFT, stroke=HexColor("#B8C9F4"), radius=12)
    badge(c, "DESIGNED / TARGET ARCHITECTURE", 58, 416, bg=BLUE, fg=WHITE, size=6.8)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(58, 385, "AWS EKS platform system")
    draw_bullets(
        c,
        [
            "RDS, S3, SQS and EKS service boundaries",
            "workload-isolated processing, training, and serving",
            "Karpenter dynamic GPU NodePool and guardrails",
            "Outbox, idempotency, conditional updates, reconciliation",
            "KServe, MLflow, observability, security, CI/CD and GitOps",
        ],
        58,
        359,
        327,
        size=7.4,
        leading=9.5,
        gap=4,
        dot_color=BLUE,
    )
    rounded_rect(c, 438, 255, 361, 195, fill=GREEN_SOFT, stroke=HexColor("#ABD2C0"), radius=12)
    badge(c, "IMPLEMENTED / REPOSITORY EVIDENCE", 454, 416, bg=GREEN, fg=WHITE, size=6.8)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(454, 385, "Limited API and data foundation")
    draw_bullets(
        c,
        [
            "FastAPI Dataset API: create, detail, update, delete + health",
            "PostgreSQL schema with 14 tables and Alembic migrations 0001-0004",
            "transactional audit logging, soft delete, aggregate query behavior",
            "Docker Compose development path and automated tests",
            "No claim of deployed EKS, Karpenter, KServe, MLflow, or GitOps",
        ],
        454,
        359,
        327,
        size=7.4,
        leading=9.5,
        gap=4,
        dot_color=GREEN,
    )

    label(c, "DECISION LINEAGE", 42, 230, PURPLE)
    flow_node(c, "Workload facts", 42, 164, 130, 45, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE)
    flow_node(c, "Architecture decision", 195, 164, 145, 45, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE)
    flow_node(c, "Failure mechanics", 363, 164, 130, 45, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE)
    flow_node(c, "Operational signals", 516, 164, 130, 45, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE)
    flow_node(c, "Evidence boundary", 669, 164, 130, 45, fill=PURPLE_SOFT, stroke=PURPLE, fg=PURPLE)
    for xx1, xx2 in [(172, 195), (340, 363), (493, 516), (646, 669)]:
        arrow(c, xx1, 186, xx2 - 4, 186, color=PURPLE)

    # Clickable links.
    rounded_rect(c, 42, 70, 361, 70, fill=NAVY, stroke=NAVY, radius=10)
    c.setFillColor(HexColor("#7EA4FF"))
    c.setFont("Helvetica-Bold", 6.7)
    c.drawString(58, 117, "LIVE ARCHITECTURE PORTFOLIO")
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 8.3)
    c.drawString(58, 94, portfolio_url)
    c.linkURL(portfolio_url, (51, 80, 394, 129), relative=0, thickness=0)
    rounded_rect(c, 438, 70, 361, 70, fill=WHITE, stroke=LINE, radius=10)
    c.setFillColor(BLUE)
    c.setFont("Helvetica-Bold", 6.7)
    c.drawString(454, 117, "SOURCE REPOSITORY")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 8.3)
    c.drawString(454, 94, repo_url)
    c.linkURL(repo_url, (447, 80, 790, 129), relative=0, thickness=0)
    footer(c, 11)
    c.showPage()


def validate_sources(repo_root: Path) -> None:
    required = [
        "docs/architecture/system-context-v3.md",
        "docs/architecture/architecture-decisions-v3.md",
        "docs/architecture/data-model-v5.md",
        "docs/architecture/state-transitions-v4.md",
        "docs/architecture/analysis-security-resilience-design.md",
        "docs/architecture/training-pipeline-design.md",
        "docs/architecture/model-serving-design.md",
        "docs/diagrams/overall-system-architecture.svg",
        "database/schema-v2.sql",
        "app/main.py",
    ]
    missing = [name for name in required if not (repo_root / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing source-of-truth files: {', '.join(missing)}")


def build_pdf(output: Path, repo_root: Path) -> None:
    validate_sources(repo_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=landscape(A4), pageCompression=1)
    c.setTitle("ArgMax Mini - AWS EKS-based MLOps Platform Architecture")
    c.setAuthor("ArgMax Mini Architecture Portfolio")
    c.setSubject("Evidence-led target architecture for an AWS EKS ML platform")
    c.setKeywords("AWS, EKS, Kubernetes, Karpenter, SRE, DevOps, MLOps, architecture")
    page_cover(c)
    page_workloads(c)
    page_architecture(c)
    page_capacity(c)
    page_failure(c)
    page_reliability(c)
    page_observability(c)
    page_security(c)
    page_gitops(c)
    page_tradeoffs(c)
    page_evidence(
        c,
        "https://naladoodong.github.io/Kubernetes-EKS-MLOps/",
        "https://github.com/naladoodong/Kubernetes-EKS-MLOps",
    )
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build_pdf(args.output.resolve(), args.repo_root.resolve())
    print(args.output.resolve())


if __name__ == "__main__":
    main()
