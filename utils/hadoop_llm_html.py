"""Standalone, escaped HTML review for the blind Hadoop LLM baseline."""

import html
import json


def _esc(value):
    return html.escape(
        str(value if value is not None else ""),
        quote=True,
    )


def _percent(value):
    return f"{float(value or 0) * 100:.1f}%"


def _list(values, empty="None"):
    values = values or []
    if not values:
        return (
            '<p class="muted">'
            + _esc(empty)
            + "</p>"
        )
    return (
        "<ul>"
        + "".join(
            "<li>" + _esc(value) + "</li>"
            for value in values
        )
        + "</ul>"
    )


def _timeline(rows):
    rows = rows or []
    if not rows:
        return (
            '<p class="muted">'
            "No timeline observations returned."
            "</p>"
        )
    return (
        '<div class="timeline">'
        + "".join(
            '<div class="timeline-row">'
            '<div class="dot"></div>'
            '<div><code>'
            + _esc(row.get("evidence_id"))
            + "</code><br><span class=\"time\">"
            + _esc(row.get("timestamp"))
            + "</span><p>"
            + _esc(row.get("observation"))
            + "</p></div></div>"
            for row in rows
        )
        + "</div>"
    )


def _case_card(case, index):
    prediction = case.get(
        "prediction",
        "unknown",
    )
    answered = bool(
        case.get("answered")
    )
    correct = bool(
        case.get("correct")
    )
    if not answered:
        status = "abstained"
        status_label = "Honest abstention"
    elif correct:
        status = "correct"
        status_label = "Correct classification"
    else:
        status = "incorrect"
        status_label = "Incorrect classification"
    validation = case.get(
        "validation", {}
    ) or {}
    citations = case.get(
        "evidence_ids", []
    ) or []
    contradictions = case.get(
        "contradicting_evidence_ids",
        [],
    ) or []
    return f"""
<article class="case" data-status="{_esc(status)}">
  <div class="case-head">
    <div>
      <div class="eyebrow">CASE {index} · {_esc(case.get("case_id"))}</div>
      <h2>{_esc(prediction.replace("_", " ").title())}</h2>
    </div>
    <span class="status {status}">{_esc(status_label)}</span>
  </div>
  <div class="case-grid">
    <div><span>Model prediction</span><strong>{_esc(prediction)}</strong></div>
    <div><span>Ground truth</span><strong>{_esc(case.get("truth"))}</strong></div>
    <div><span>Confidence</span><strong>{_esc(case.get("confidence"))}</strong></div>
    <div><span>Latency</span><strong>{_esc(case.get("latency_ms"))} ms</strong></div>
  </div>
  <div class="truth-note">
    Ground truth and workload were attached only after the API response.
    They were not part of model input.
  </div>
  <h3>Model summary</h3>
  <blockquote>{_esc(case.get("summary"))}</blockquote>
  <div class="columns">
    <section>
      <h3>Supporting evidence IDs</h3>
      {_list(citations, "No supporting ID claimed.")}
      <h3>Contradicting evidence IDs</h3>
      {_list(contradictions, "No contradiction cited.")}
    </section>
    <section>
      <h3>Missing discriminating evidence</h3>
      {_list(case.get("missing_evidence"), "Nothing missing according to the model.")}
    </section>
  </div>
  <h3>Model timeline</h3>
  {_timeline(case.get("timeline"))}
  <details>
    <summary>Technical contract and usage</summary>
    <div class="technical">
      <div><span>Citations valid</span><strong>{_esc(validation.get("citation_valid"))}</strong></div>
      <div><span>Claim contract valid</span><strong>{_esc(validation.get("claim_contract_valid"))}</strong></div>
      <div><span>Evidence-pack size</span><strong>{_esc(case.get("evidence_pack_chars"))} chars</strong></div>
      <div><span>Known evidence IDs</span><strong>{_esc(case.get("known_evidence_id_count"))}</strong></div>
      <div><span>Input tokens</span><strong>{_esc((case.get("usage") or {}).get("input_tokens"))}</strong></div>
      <div><span>Output tokens</span><strong>{_esc((case.get("usage") or {}).get("output_tokens"))}</strong></div>
    </div>
  </details>
</article>
"""


def render_hadoop_llm_review(report):
    """Render one complete report without external assets or live actions."""
    metrics = report.get(
        "metrics", {}
    ) or {}
    cases = report.get("cases", []) or []
    case_html = "".join(
        _case_card(case, index)
        for index, case in enumerate(
            cases,
            start=1,
        )
    )
    contract_passed = bool(
        report.get(
            "contract_gate_passed"
        )
    )
    diagnostic_passed = bool(
        report.get(
            "diagnostic_gate_passed"
        )
    )
    provider_failures = report.get(
        "provider_failures", []
    ) or []
    usage = report.get("usage", {}) or {}
    model_names = sorted({
        str(case.get("model"))
        for case in cases
        if case.get("model")
    })
    status_title = (
        "Model contract passed; data gate needs work"
        if contract_passed
        and not diagnostic_passed
        else (
            "All configured gates passed"
            if contract_passed
            and diagnostic_passed
            else "Contract gate failed"
        )
    )
    raw_json = _esc(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hadoop × OpenAI review</title>
<style>
:root {{
  --bg: #09111f;
  --surface: #111c2e;
  --surface-2: #17253a;
  --border: #2a3b54;
  --text: #e8eef8;
  --muted: #93a4bb;
  --blue: #67a6ff;
  --green: #53d18b;
  --yellow: #f1c75b;
  --red: #ff7575;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background:
    radial-gradient(circle at 8% 0%, #18345d 0, transparent 32rem),
    var(--bg);
  color: var(--text);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
main {{ max-width: 1120px; margin: 0 auto; padding: 44px 24px 80px; }}
h1 {{ font-size: clamp(32px, 6vw, 58px); line-height: 1; margin: 8px 0 18px; }}
h2 {{ margin: 2px 0; font-size: 26px; }}
h3 {{ margin: 24px 0 8px; font-size: 14px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }}
p {{ margin: 7px 0; }}
code {{ color: #b9d7ff; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
.eyebrow {{ color: var(--blue); font-weight: 700; font-size: 12px; letter-spacing: .12em; }}
.lede {{ max-width: 760px; color: #b8c7da; font-size: 18px; }}
.banner {{
  margin: 28px 0;
  padding: 18px 20px;
  border-left: 4px solid var(--yellow);
  background: #201f1b;
  border-radius: 0 10px 10px 0;
}}
.banner strong {{ display: block; font-size: 18px; color: #ffe295; }}
.metrics {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 28px 0;
}}
.metric, .case, .method {{
  background: color-mix(in srgb, var(--surface) 94%, transparent);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 16px 50px rgb(0 0 0 / 18%);
}}
.metric {{ padding: 18px; }}
.metric span, .case-grid span, .technical span {{ display: block; color: var(--muted); font-size: 12px; }}
.metric strong {{ display: block; font-size: 25px; margin-top: 4px; }}
.toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 26px 0 14px; }}
button {{
  color: var(--text);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 8px 13px;
  cursor: pointer;
}}
button.active {{ border-color: var(--blue); color: #cfe3ff; background: #18365c; }}
.case {{ padding: 24px; margin: 14px 0; }}
.case.hidden {{ display: none; }}
.case-head {{ display: flex; align-items: center; justify-content: space-between; gap: 14px; }}
.status {{ padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
.status.correct {{ color: #07170e; background: var(--green); }}
.status.abstained {{ color: #241b04; background: var(--yellow); }}
.status.incorrect {{ color: #260808; background: var(--red); }}
.case-grid, .technical {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 18px 0;
}}
.case-grid > div, .technical > div {{
  padding: 10px 12px;
  background: var(--surface-2);
  border-radius: 8px;
}}
.truth-note {{
  color: #bad7ff;
  background: #102746;
  border: 1px solid #294c75;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
}}
blockquote {{
  margin: 0;
  padding: 16px 18px;
  border-left: 3px solid var(--blue);
  background: #0d1727;
  border-radius: 0 8px 8px 0;
  font-size: 17px;
}}
.columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
ul {{ margin: 6px 0; padding-left: 21px; }}
.muted, .time {{ color: var(--muted); }}
.timeline {{ border-left: 1px solid var(--border); margin-left: 7px; }}
.timeline-row {{ display: grid; grid-template-columns: 22px 1fr; margin: 10px 0; }}
.dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--blue); margin: 7px 0 0 -5px; }}
.timeline-row p {{ color: #c7d3e3; }}
details {{ margin-top: 20px; border-top: 1px solid var(--border); padding-top: 14px; }}
summary {{ cursor: pointer; color: var(--blue); }}
.method {{ padding: 20px; margin: 28px 0; }}
.method-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
pre {{
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 520px;
  overflow: auto;
  background: #050a12;
  padding: 16px;
  border-radius: 8px;
  color: #b8c7da;
}}
@media (max-width: 780px) {{
  .metrics, .case-grid, .technical {{ grid-template-columns: 1fr 1fr; }}
  .columns, .method-grid {{ grid-template-columns: 1fr; }}
  .case-head {{ align-items: flex-start; flex-direction: column; }}
}}
</style>
</head>
<body>
<main>
  <div class="eyebrow">BLIND EVALUATION · {_esc(report.get("prompt_version"))}</div>
  <h1>Hadoop × OpenAI review</h1>
  <p class="lede">
    A reviewer-first view of the exact structured model findings. Dataset truth
    is displayed for evaluation, but was held out until after every API response.
  </p>

  <div class="banner">
    <strong>{_esc(status_title)}</strong>
    The model stayed grounded and abstained when the evidence pack could not
    distinguish the failure class. Improve sampling and evidence selection
    before encouraging more classifications.
  </div>

  <section class="metrics" aria-label="Evaluation metrics">
    <div class="metric"><span>API success</span><strong>{_esc(report.get("cases_successful"))}/{_esc(report.get("cases_requested"))}</strong></div>
    <div class="metric"><span>Citation validity</span><strong>{_percent(metrics.get("citation_valid_rate"))}</strong></div>
    <div class="metric"><span>Coverage</span><strong>{_percent(metrics.get("coverage"))}</strong></div>
    <div class="metric"><span>Recoverable accuracy</span><strong>{_percent(metrics.get("recoverable_selective_accuracy", metrics.get("selective_accuracy")))}</strong></div>
  </section>

  <section class="method">
    <div class="method-grid">
      <div>
        <h3>What the model saw</h3>
        <p>Blind case ID, compact evidence pack, event IDs and the fixed
        classification contract.</p>
      </div>
      <div>
        <h3>What stayed hidden</h3>
        <p>Application ID, workload and dataset truth. Those fields were joined
        only after the response for scoring and this review.</p>
      </div>
    </div>
    <p class="muted">Model: {_esc(", ".join(model_names))} · Input tokens:
    {_esc(usage.get("input_tokens"))} · Output tokens:
    {_esc(usage.get("output_tokens"))} · Provider failures:
    {_esc(len(provider_failures))}</p>
  </section>

  <div class="toolbar" aria-label="Case filters">
    <button class="active" data-filter="all">All cases</button>
    <button data-filter="correct">Correct</button>
    <button data-filter="abstained">Abstained</button>
    <button data-filter="incorrect">Incorrect</button>
  </div>
  <section id="cases">{case_html}</section>

  <details>
    <summary>Complete machine-readable evaluation</summary>
    <pre>{raw_json}</pre>
  </details>
</main>
<script>
for (const button of document.querySelectorAll("[data-filter]")) {{
  button.addEventListener("click", () => {{
    const filter = button.dataset.filter;
    for (const item of document.querySelectorAll(".case")) {{
      item.classList.toggle("hidden", filter !== "all" && item.dataset.status !== filter);
    }}
    for (const peer of document.querySelectorAll("[data-filter]")) {{
      peer.classList.toggle("active", peer === button);
    }}
  }});
}}
</script>
</body>
</html>
"""
