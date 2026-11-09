#!/usr/bin/env python3
"""Build the report PDF from report.md, filling every number from the evaluation outputs.

    python report/build_report.py --video-url https://youtu.be/XXXX
    python report/build_report.py --out ~/Desktop/COSC726_Project_OmairGibreel_Report.pdf

Needs pandoc and Google Chrome/Chromium (headless print to PDF). Numbers come from
evals/results/summary.json and evals/results/llm/llm_summary.json, so the report cannot drift
from the evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO_URL = "https://github.com/comrade1996/cosc726-omairgibreel"
CHROME = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser"]
sys.path.insert(0, str(ROOT))

from evals.run_eval import TABLE_ROWS  # noqa: E402

CSS = """
@page { size: A4; margin: 20mm 18mm 20mm 18mm; }
body { font-family: "Georgia", "Times New Roman", serif; font-size: 10.6pt; line-height: 1.42; color: #111; }
h1, h2, h3 { font-family: "Helvetica Neue", Arial, sans-serif; color: #1f3b57; }
h2 { font-size: 14pt; margin: 18px 0 6px; border-bottom: 1px solid #c9d3dd; padding-bottom: 2px; }
h3 { font-size: 11.5pt; margin: 12px 0 4px; }
h2, h3 { page-break-after: avoid; break-after: avoid; }
p { margin: 5px 0; text-align: justify; }
table { border-collapse: collapse; margin: 8px 0; font-size: 8.6pt; width: 100%; page-break-inside: avoid; }
th, td { border: 1px solid #c9d3dd; padding: 3px 5px; vertical-align: top; }
th { background: #eef2f6; text-align: left; }
code { font-size: 8.8pt; background: #f3f5f7; padding: 0 2px; }
pre { font-size: 8.2pt; background: #f3f5f7; padding: 6px; white-space: pre-wrap; }
figure { text-align: center; margin: 8px 0; page-break-inside: avoid; }
figcaption { font-size: 8.8pt; color: #444; }
img { max-width: 100%; }
header#title-block-header { display: none; }
.titlepage { page-break-after: always; padding-top: 55mm; }
.tp-module { font-family: Arial, sans-serif; color: #5b6b7f; font-size: 11pt; }
.tp-title { font-size: 26pt; margin: 10px 0 4px; border: none; }
.tp-sub { font-size: 13pt; color: #333; margin-bottom: 26px; }
.tp-table td { font-size: 10.5pt; border: none; border-bottom: 1px solid #e3e8ee; padding: 6px 4px; }
.tp-table td:first-child { width: 34%; color: #5b6b7f; font-family: Arial, sans-serif; }
.tp-note { margin-top: 30px; font-size: 9.5pt; color: #444; border-left: 3px solid #1f3b57; padding-left: 8px; }
.pagebreak { page-break-after: always; }
"""


def fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if v <= 1 else f"{v:.1f}"
    return str(v)


def main_table(summary: dict) -> str:
    cfgs = list(summary)
    head = "| Metric | " + " | ".join(f"{c}" for c in cfgs) + " |\n|---|" + "---|" * len(cfgs) + "\n"
    rows = []
    for label, key in TABLE_ROWS:
        vals = [" / ".join(fmt(summary[c][k]) for k in key) if isinstance(key, tuple) else fmt(summary[c][key]) for c in cfgs]
        rows.append(f"| {label} | " + " | ".join(vals) + " |")
    return head + "\n".join(rows)


def llm_table(s: dict) -> str:
    keep = [("Correct completion (expected sent)", "correct_completion_rate"), ("Safe-block rate (expected blocked)", "safe_block_rate"),
            ("Unsafe handoffs sent", "unsafe_sent"), ("Endpoint errors", "endpoint_errors"), ("Stop reasons", "stop_reasons"),
            ("Unknown-tool calls attempted", "unknown_tool_calls"), ("Undeclared-argument calls", "schema_errors"),
            ("Out-of-scope case calls attempted", "out_of_scope_calls_attempted"),
            ("Confirm attempts on blocked cases", "confirm_attempts_on_blocked_cases"), ("Critic rejections (replans)", "critic_rejections"),
            ("Invented values in final answers", "invented_values_in_final"),
            ("Blocked escalations naming every gap", "blocked_escalations_naming_all_gaps"),
            ("Injection cases where the model complied", "injection_cases_where_model_complied"),
            ("Latency per case p50 / p95 (s)", ("latency_p50_s", "latency_p95_s")), ("Mean turns", "mean_turns")]
    out = ["| Metric | Qwen2.5-7B-Instruct on C4 |", "|---|---|"]
    for label, key in keep:
        if isinstance(key, tuple):
            val = " / ".join(fmt(s.get(k)) for k in key)
        elif isinstance(s.get(key), dict):
            val = ", ".join(f"{k}: {v}" for k, v in s[key].items())
        else:
            val = fmt(s.get(key))
        out.append(f"| {label} | {val} |")
    return "\n".join(out)


def build_values(video_url: str) -> dict:
    det = json.loads((ROOT / "evals/results/summary.json").read_text())
    llm_path = ROOT / "evals/results/llm/llm_summary.json"
    llm = json.loads(llm_path.read_text()) if llm_path.exists() else None
    S = det["summary"]
    v = {"REPO_URL": REPO_URL, "VIDEO_URL": video_url, "DATE": date.today().strftime("%d %B %Y"),
         "TABLE_MAIN": main_table(S), "META.git_commit": det["meta"]["git_commit"], "META.generated_at": det["meta"]["generated_at"],
         "META.versions": ", ".join(f"{k} {val}" for k, val in det["meta"]["versions"].items())}
    for cfg, row in S.items():
        for k, val in row.items():
            v[f"{cfg}.{k}"] = fmt(val)
    v["OVERHEAD.mcp_ms"] = fmt(round(S["C3"]["latency_p50_ms"] - S["C2"]["latency_p50_ms"], 1))
    probe = det["discovery"]["http_security_probe"] if det.get("discovery") else {}
    v["DISCOVERY.probe"] = "/".join(str(probe.get(k)) for k in ("no_token", "forged_token", "foreign_origin"))
    if llm:
        L, rq3 = llm["summary"], llm.get("rq3_missing_fields") or {}
        for k, val in L.items():
            v[f"LLM.{k}"] = fmt(val) if not isinstance(val, dict) else json.dumps(val)
        v["LLM.correct_completion_pct"] = f"{round(100 * (L['correct_completion_rate'] or 0))}%"
        v["TABLE_LLM"] = llm_table(L)
        v["RQ3.precision"], v["RQ3.recall"] = fmt(rq3.get("precision")), fmt(rq3.get("recall"))
        v["LLM.narrative"] = llm.get("narrative") or (HERE / "llm_narrative.md").read_text().strip()
        v["RQ3.sentence"] = (HERE / "rq3_sentence.md").read_text().strip() if (HERE / "rq3_sentence.md").exists() else ""
    return v


def render(md: str, values: dict) -> str:
    def sub(m):
        key = m.group(1)
        if key not in values:
            raise SystemExit(f"report.md references {{{{{key}}}}} but no value exists")
        return values[key]
    # Two passes: narrative snippets may themselves contain placeholders.
    return re.sub(r"\{\{([\w.]+)\}\}", sub, re.sub(r"\{\{([\w.]+)\}\}", sub, md))


def body_words(md: str) -> int:
    body = md.split("<!-- BODY-START -->")[1].split("<!-- BODY-END -->")[0]
    body = re.sub(r"(?m)^\|.*\|$", " ", body)            # tables
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)\{[^}]*\}", " ", body)  # figures
    body = re.sub(r"(?m)^\*Table \d.*$", " ", body)         # table captions
    body = re.sub(r"[#*`>_]", " ", body)
    return len(re.findall(r"[A-Za-z0-9][\w'./%-]*", body))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video-url", default="VIDEO_URL_PLACEHOLDER")
    ap.add_argument("--out", type=Path, default=ROOT.parent / "COSC726_Project_OmairGibreel_Report.pdf")
    args = ap.parse_args()
    values = build_values(args.video_url)
    raw = (HERE / "report.md").read_text()
    md = render(raw.replace("{{WORDS}}", "@@WORDS@@"), {**values, "WORDS": "@@WORDS@@"})
    words = body_words(md)
    md = md.replace("@@WORDS@@", f"{words:,}")
    build = HERE / "build"
    build.mkdir(exist_ok=True)
    (build / "report.filled.md").write_text(md)
    (build / "style.css").write_text(CSS)
    html = build / "report.html"
    subprocess.run(["pandoc", str(build / "report.filled.md"), "-f", "markdown+fenced_divs+pipe_tables+implicit_figures",
                    "-s", "--css", "style.css", "--metadata", "pagetitle=COSC726 Project Report - Omair Gibreel",
                    "--resource-path", str(HERE), "--embed-resources", "-o", str(html)], check=True, cwd=build)
    chrome = next((c for c in CHROME if Path(c).exists() or shutil.which(c)), None)
    if not chrome:
        raise SystemExit(f"Chrome/Chromium not found; open {html} in a browser and print to PDF.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={args.out}",
                    html.as_uri()], check=True, capture_output=True)
    print(f"Wrote {args.out} ({words} body words)")


if __name__ == "__main__":
    main()
