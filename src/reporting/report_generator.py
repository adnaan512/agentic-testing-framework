"""Generates a self-contained HTML report."""

import html
from pathlib import Path
from src.models import Anomaly, Severity, TestCase

_SEVERITY_COLORS = {
    Severity.CRITICAL: "#b91c1c",
    Severity.HIGH: "#c2410c",
    Severity.MEDIUM: "#a16207",
    Severity.LOW: "#0369a1",
    Severity.INFO: "#374151",
}

def _esc(text): return html.escape(str(text))

def generate_html_report(target_url, anomalies, test_cases, visited_count, output_path):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("<html><body><h1>Report placeholder</h1></body></html>")
    return output_path
