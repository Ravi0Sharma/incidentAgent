import html
import json
import re

from settings import (
    REVIEW_API_BASE
)
from utils.redaction import redact_data
from utils.review_gate import (
    analysis_review_state,
)


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #0d1117;
    --panel: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --muted: #8b949e;
    --accent: #58a6ff;
    --sev1: #f85149;
    --sev2: #db6d28;
    --sev3: #d29922;
    --sev4: #3fb950;
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system,
      Segoe UI, sans-serif;
    max-width: 960px;
    margin: 40px auto;
    padding: 0 24px;
    line-height: 1.55;
  }}
  h1, h2, h3 {{
    color: var(--text);
    border-bottom: 1px solid
      var(--border);
    padding-bottom: 6px;
    margin-top: 32px;
  }}
  .sev {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 4px;
    font-weight: 600;
    color: #0d1117;
  }}
  .sev-SEV1 {{
    background: var(--sev1);
  }}
  .sev-SEV2 {{
    background: var(--sev2);
  }}
  .sev-SEV3 {{
    background: var(--sev3);
  }}
  .sev-SEV4 {{
    background: var(--sev4);
  }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
    margin: 12px 0;
  }}
  pre {{
    background: #010409;
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 13px;
    color: var(--text);
  }}
  .heatmap {{
    font-family:
      SF Mono, Menlo, monospace;
    font-size: 12px;
    line-height: 1.4;
    white-space: pre;
  }}
  details {{
    margin: 8px 0;
  }}
  summary {{
    cursor: pointer;
    color: var(--accent);
  }}
  .kv {{
    display: grid;
    grid-template-columns:
      140px 1fr;
    gap: 4px 16px;
  }}
  .kv b {{
    color: var(--muted);
    font-weight: 500;
  }}
  .pills span {{
    display: inline-block;
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--accent);
    padding: 1px 8px;
    border-radius: 10px;
    margin: 2px 4px 2px 0;
    font-size: 12px;
  }}
  .md h1, .md h2, .md h3 {{
    margin-top: 20px;
  }}
  .md ul {{
    margin: 8px 0;
    padding-left: 22px;
  }}
  .md li {{
    margin: 3px 0;
  }}
  .md p {{
    margin: 8px 0;
  }}
  .md code {{
    background: #010409;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 13px;
  }}
  .md table {{
    border-collapse: collapse;
    margin: 12px 0;
    width: 100%;
  }}
  .md th, .md td {{
    border: 1px solid var(--border);
    padding: 6px 10px;
    text-align: left;
    font-size: 14px;
  }}
  .md th {{
    background: #010409;
    color: var(--muted);
  }}
  .md a {{
    color: var(--accent);
  }}
</style>
</head>
<body>

<h1>{title}</h1>

<div class="panel">
  <div class="kv">
    <b>Incident ID</b>
    <span>{incident_id}</span>
    <b>Severity</b>
    <span>
      <span class="sev sev-{sev}">
        {sev}
      </span>
      &nbsp;{sev_reason}
    </span>
    <b>Service</b>
    <span>{service}
      (tier {tier},
      owner {owner})</span>
    <b>Runbook</b>
    <span>{runbook}</span>
  </div>
</div>

<h2>Executive summary &amp; postmortem</h2>
<div class="panel md">{postmortem}</div>

<h2>5-Whys drilldown</h2>
<div class="panel md">{rca}</div>

<h2>Error frequency (per minute)</h2>
<div class="panel heatmap">{heatmap}</div>

<h2>Anchor event</h2>
<div class="panel">
<pre>{anchor}</pre>
</div>

<h2>Timeline</h2>
<div class="panel">
{timeline_rows}
</div>

<h2>Detection rules matched</h2>
<div class="panel">
{detections}
</div>

<h2>Pivot keywords</h2>
<div class="panel pills">
{pivots}
</div>

<h2>Top log groups (post-suppression)</h2>
<div class="panel">
{log_groups}
</div>

<details>
<summary>Raw interpretation
(all 3 hypotheses)</summary>
<div class="panel md">
{interpretation}
</div>
</details>

</body>
</html>
"""


_REVIEW_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #0d1117;
    --panel: #161b22;
    --panel2: #0f1623;
    --border: #30363d;
    --text: #c9d1d9;
    --muted: #8b949e;
    --accent: #58a6ff;
    --ok: #3fb950;
    --warn: #d29922;
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system,
      Segoe UI, sans-serif;
    max-width: 1040px;
    margin: 32px auto;
    padding: 0 24px 48px;
    line-height: 1.55;
  }}
  h1, h2, h3 {{
    color: var(--text);
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
    margin-top: 28px;
  }}
  .panel {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px 20px;
    margin: 12px 0;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }}
  .tile {{
    background: var(--panel2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    min-height: 86px;
  }}
  .tile b {{
    display: block;
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 6px;
  }}
  .source-grid {{
    display: grid;
    grid-template-columns:
      repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
  }}
  .source-card {{
    background: var(--panel2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
  }}
  .source-card h3 {{
    margin: 0 0 10px;
    border: 0;
    padding: 0;
  }}
  .source-card dl {{
    display: grid;
    grid-template-columns: 120px 1fr;
    gap: 5px 10px;
    margin: 0;
  }}
  .source-card dt {{
    color: var(--muted);
  }}
  .source-card dd {{
    margin: 0;
    overflow-wrap: anywhere;
  }}
  .signal {{
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 8px 14px;
  }}
  .signal b {{
    color: var(--muted);
    font-weight: 500;
  }}
  .checklist label {{
    display: block;
    margin: 8px 0;
  }}
  .checklist input {{
    margin-right: 8px;
  }}
  details.technical {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin: 16px 0;
    padding: 12px 16px;
  }}
  details.technical > summary {{
    cursor: pointer;
    color: var(--accent);
    font-weight: 700;
  }}
  .timeline-note {{
    color: var(--muted);
    margin-bottom: 10px;
  }}
  .cmd {{
    display: block;
    background: #010409;
    padding: 10px 12px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 8px 0;
  }}
  .decision {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }}
  .decision code {{
    display: block;
    background: #010409;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
  }}
  .decision .only {{
    grid-column: 1 / -1;
  }}
  .approve {{
    border-left: 4px solid var(--ok);
  }}
  .reject {{
    border-left: 4px solid var(--warn);
  }}
  pre {{
    background: #010409;
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 13px;
    color: var(--text);
    white-space: pre-wrap;
  }}
  .md h1, .md h2, .md h3 {{
    margin-top: 18px;
  }}
  .md ul {{
    margin: 8px 0;
    padding-left: 22px;
  }}
  .md li {{
    margin: 3px 0;
  }}
  .md code {{
    background: #010409;
    padding: 1px 5px;
    border-radius: 4px;
  }}
  .muted {{
    color: var(--muted);
  }}
  .risk {{
    color: var(--warn);
  }}
  select, textarea {{
    background: #010409;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 12px;
    font: inherit;
  }}
  textarea {{
    width: 100%;
    min-height: 92px;
    resize: vertical;
    box-sizing: border-box;
  }}
  button {{
    border: 0;
    border-radius: 6px;
    padding: 10px 14px;
    color: #fff;
    background: #2563eb;
    font-weight: 700;
    cursor: pointer;
  }}
  button:hover {{
    filter: brightness(1.12);
  }}
  button.reject-btn {{
    background: #a13a3a;
  }}
  .status-msg {{
    min-height: 20px;
    color: var(--muted);
  }}
  .status-msg.working {{
    color: var(--warn);
  }}
  .status-msg.done {{
    color: var(--ok);
  }}
  .status-msg.error {{
    color: #ff8888;
  }}
  @media (max-width: 760px) {{
    .grid {{
      grid-template-columns: 1fr;
    }}
    .decision {{
      grid-template-columns: 1fr;
    }}
    .signal {{
      grid-template-columns: 1fr;
    }}
  }}
</style>
</head>
<body>

<h1>{title}</h1>

<div class="panel">
  <b>Status:</b> awaiting human review<br>
  <b>Attempt:</b> {attempt}<br>
  <span class="muted">
    Reviewer chooses a hypothesis or rejects with feedback.
  </span>
  <br>
  <span class="muted">
    Buttons only work while this exact incident is pending in the
    currently running webhook server. Static files in output/ are
    snapshots; after a server restart, start a fresh incident from
    the webhook home page.
  </span>
  {analysis_status}
</div>

<h2>At a Glance</h2>
<div class="grid">
  <div class="tile">
    <b>Severity</b>
    {severity}<br>
    <span class="muted">{severity_reason}</span>
  </div>
  <div class="tile">
    <b>Service</b>
    {service}<br>
    <span class="muted">owner {owner}, tier {tier}</span>
  </div>
  <div class="tile">
    <b>Likely Cause</b>
    {top_detection}<br>
    <span class="muted">{top_category}</span>
  </div>
  <div class="tile">
    <b>Scale</b>
    {raw_log_count} raw logs<br>
    <span class="muted">{log_group_count} groups, {detection_count} rules</span>
  </div>
</div>

<h2>Decision Signals</h2>
<div class="panel signal">
  <b>Anchor</b>
  <span>{anchor}</span>
  <b>Top log group</b>
  <span>{top_group}</span>
  <b>Recent deploy</b>
  <span>{top_deploy}</span>
  <b>Metrics</b>
  <span>{metric_summary}</span>
  <b>Pivots</b>
  <span>{pivot_summary}</span>
  <b>Known gap</b>
  <span class="risk">{known_gap}</span>
</div>

<h2>Incident Timeline</h2>
<div class="panel">
{review_timeline}
</div>

<h2>Analysis For Decision</h2>
<div class="panel md">{interpretation}</div>

<h2>What Remains Unknown</h2>
<div class="panel risk">
<pre>{unknowns}</pre>
</div>

<h2>Evidence Coverage</h2>
<div class="panel">
{evidence_coverage}
</div>

<h2>Evidence Expansion Outcome</h2>
<div class="panel">
{investigation_outcome}
</div>

<h2>Verification Prompts</h2>
<div class="panel">
  <span class="muted">
    Useful checks before approving or rejecting.
  </span>
  {verification_commands}
</div>

<h2>Reviewer Checklist</h2>
<div class="panel checklist">
  <label><input type="checkbox"> Evidence cites concrete labels, counts, timestamps, rule IDs, pivots.</label>
  <label><input type="checkbox"> Hypothesis 1 explains the anchor event and top severity signal.</label>
  <label><input type="checkbox"> Alternative hypotheses have real weaknesses, not filler.</label>
  <label><input type="checkbox"> Suggested action is safe to propose and has a verification step.</label>
  <label><input type="checkbox"> Missing data does not change the likely root cause.</label>
</div>

<h2>Decision Commands</h2>
<div class="decision">
  {decision_controls}
</div>
<p id="reviewStatus" class="status-msg"></p>

<h2>Good Rejection Feedback</h2>
<div class="panel">
<pre>{feedback_examples}</pre>
</div>

<details class="technical">
<summary>Technical validation, provenance, and model details</summary>
<h3>Interpretation Guardrails</h3>
<pre>{interpretation_quality}</pre>
<h3>Claim Grounding</h3>
<pre>{claim_grounding}</pre>
<h3>Deterministic Candidate Assessment</h3>
<pre>{deterministic_assessment}</pre>
<h3>Investigation Budget</h3>
<pre>{investigation_budget}</pre>
<h3>Model Usage And Deadline</h3>
<pre>{model_usage_and_deadline}</pre>
<h3>Semantic Correlation</h3>
<pre>{semantic_correlation}</pre>
<h3>Correlation Tool Searches</h3>
<pre>{semantic_tool_trace}</pre>
<h3>Evidence Pack Prepared For Interpretation</h3>
<pre>{evidence_pack}</pre>
<h3>Metrics</h3>
<pre>{metrics}</pre>
<h3>Deploys</h3>
<pre>{deploys}</pre>
</details>

<script>
const API_BASE = {api_base_json};
const INCIDENT_ID = {incident_id_json};
let pendingRevision = null;
let csrfToken = null;

function reviewEndpoint() {{
  const apiOrigin = new URL(API_BASE).origin;
  if (
    (
      window.location.protocol === "http:" ||
      window.location.protocol === "https:"
    ) &&
    window.location.origin === apiOrigin
  ) {{
    return window.location.origin + "/alerts/" + INCIDENT_ID + "/review";
  }}
  return API_BASE.replace(/\/$/, "") + "/alerts/" + INCIDENT_ID + "/review";
}}

function reviewStatusEndpoint() {{
  return reviewEndpoint() + "/status";
}}

function setStatus(kind, text) {{
  const el = document.getElementById("reviewStatus");
  el.className = "status-msg " + kind;
  el.textContent = text;
}}

function setDecisionDisabled(disabled) {{
  document
    .querySelectorAll(".decision button, .decision select, .decision textarea")
    .forEach(function(el) {{
      el.disabled = disabled;
    }});
}}

function explainServerError(data, fallback) {{
  if (!data) {{
    return fallback;
  }}
  return (
    data.error ||
    data.recovery ||
    fallback
  ) + (data.recovery ? " " + data.recovery : "");
}}

function checkPendingReview() {{
  setDecisionDisabled(true);
  setStatus("working", "Checking pending review state...");
  return fetch(reviewStatusEndpoint())
    .then(function(response) {{
      return response.json().then(function(data) {{
        if (!response.ok) {{
          throw new Error(explainServerError(data, "HTTP " + response.status));
        }}
        return data;
      }});
    }})
    .then(function(data) {{
      if (data.awaiting_review) {{
        pendingRevision = data.pending_revision;
        csrfToken = data.csrf_token;
        setDecisionDisabled(false);
        setStatus("done", "Connected to pending review. Ready.");
      }} else {{
        setDecisionDisabled(true);
        setStatus(
          "error",
          explainServerError(
            data,
            "This review snapshot is not pending in the webhook server."
          )
        );
      }}
    }})
    .catch(function(error) {{
      setDecisionDisabled(true);
      setStatus(
        "error",
        "Could not check review state: " + error.message +
        ". Open the webhook home page at " + API_BASE + " and start a fresh demo incident."
      );
    }});
}}

function postReview(payload) {{
  if (pendingRevision === null) {{
    setStatus("error", "Review revision is unavailable; reload the page.");
    return Promise.resolve();
  }}
  payload.pending_revision = pendingRevision;
  setStatus("working", "Processing review...");
  return fetch(reviewEndpoint(), {{
    method: "POST",
    headers: {{
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken
    }},
    body: JSON.stringify(payload)
  }})
    .then(function(response) {{
      return response.json().then(function(data) {{
        if (!response.ok) {{
          throw new Error(
            explainServerError(
              data,
              "HTTP " + response.status
            )
          );
        }}
        return data;
      }});
    }})
    .then(function(data) {{
      if (data.awaiting_review) {{
        setStatus(
          "done",
          data.review_status === "request_more_evidence"
            ? "More evidence requested. Refresh to review the new analysis."
            : "Rejected. Agent produced a new interpretation; refresh the incident UI."
        );
      }} else {{
        setStatus("done", "Approved. RCA/postmortem flow continued.");
      }}
    }})
    .catch(function(error) {{
      setStatus(
        "error",
        "Review POST failed: " + error.message +
        "."
      );
    }});
}}

function approveReview() {{
  postReview({{
    status: "approved",
    chosen_hypothesis: parseInt(
      document.getElementById("chosenHypothesis").value,
      10
    )
  }});
}}

function rejectReview() {{
  postReview({{
    status: "rejected",
    feedback: document.getElementById("reviewFeedback").value
  }});
}}

function requestMoreEvidence() {{
  postReview({{
    status: "request_more_evidence",
    feedback: document.getElementById("reviewFeedback").value
  }});
}}

checkPendingReview();
</script>

</body>
</html>
"""


def _esc(v):
    from utils.render_safety import bounded_text
    return html.escape(
        bounded_text(v)
    )


def _inline_md(text):
    """Inline markdown on an already HTML-escaped string."""

    text = re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
        text
    )
    text = re.sub(
        r"`([^`]+?)`",
        r"<code>\1</code>",
        text
    )
    text = re.sub(
        r"\[([^\]]+?)\]\((https?://[^)]+?)\)",
        r'<a href="\2">\1</a>',
        text
    )

    return text


def _md_to_html(md):
    """Minimal markdown -> HTML for postmortem / RCA / interpretation.

    Handles h1-h3, bold, inline code, links, bullet lists,
    pipe tables, horizontal rules and paragraphs. Escapes first
    so raw HTML in the model output can't inject markup.
    """

    if not md:
        return ""

    from utils.render_safety import bounded_text
    lines = bounded_text(md).split("\n")
    out = []
    list_open = False
    table_buf = []

    def _close_list():
        nonlocal list_open
        if list_open:
            out.append("</ul>")
            list_open = False

    def _flush_table():
        if not table_buf:
            return
        rows = [
            r for r in table_buf
            if not re.match(
                r"^\s*\|?[\s:|-]+\|?\s*$",
                r
            )
        ]
        cells = [
            [
                _inline_md(
                    _esc(c.strip())
                )
                for c in re.split(
                    r"\s*\|\s*",
                    r.strip().strip("|")
                )
            ]
            for r in rows
        ]
        if cells:
            out.append("<table>")
            head, *body = cells
            out.append(
                "<tr>"
                + "".join(
                    f"<th>{c}</th>"
                    for c in head
                )
                + "</tr>"
            )
            for row in body:
                out.append(
                    "<tr>"
                    + "".join(
                        f"<td>{c}</td>"
                        for c in row
                    )
                    + "</tr>"
                )
            out.append("</table>")
        table_buf.clear()

    for raw in lines:

        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("|") and "|" in stripped[1:]:
            _close_list()
            table_buf.append(line)
            continue
        else:
            _flush_table()

        if not stripped:
            _close_list()
            continue

        if re.match(r"^#{1,6}\s", stripped):
            _close_list()
            level = len(
                stripped
            ) - len(
                stripped.lstrip("#")
            )
            level = min(
                max(level, 1), 3
            )
            content = _inline_md(
                _esc(
                    stripped[level:]
                    .strip()
                )
            )
            out.append(
                f"<h{level}>{content}"
                f"</h{level}>"
            )
            continue

        if stripped in ("---", "***", "___"):
            _close_list()
            out.append("<hr>")
            continue

        m = re.match(
            r"^[-*]\s+(.*)$",
            stripped
        )
        if m:
            if not list_open:
                out.append("<ul>")
                list_open = True
            out.append(
                "<li>"
                + _inline_md(
                    _esc(m.group(1))
                )
                + "</li>"
            )
            continue

        _close_list()
        out.append(
            "<p>"
            + _inline_md(_esc(stripped))
            + "</p>"
        )

    _flush_table()
    _close_list()

    return "\n".join(out)


def _render_timeline(events):

    if not events:
        return "(no events)"

    rows = []

    for e in events:

        marker = (
            " <b>ANCHOR</b>"
            if e.get("is_anchor")
            else ""
        )

        labels = (
            e.get("labels")
            or e.get("commit")
            or ""
        )
        burst = e.get("burst", {}) or {}
        burst_text = ""
        if burst.get(
            "collapsed_repetition"
        ):
            burst_text = (
                " — collapsed burst: "
                + str(
                    burst.get(
                        "repetitions", 0
                    )
                )
                + " events, "
                + str(
                    burst.get(
                        "distinct_time_buckets",
                        0,
                    )
                )
                + " buckets, peak "
                + str(
                    burst.get(
                        "peak_count", 0
                    )
                )
            )

        rows.append(
            f"<div><code>"
            f"{_esc(e.get('offset', 'T?'))}"
            f"</code>{marker} "
            f"<b>[{_esc(e.get('type'))}]"
            f"</b> "
            f"{_esc(e.get('timestamp'))} "
            f"— {_esc(labels)}"
            f"{_esc(burst_text)}</div>"
        )

    return "\n".join(rows)


def _review_timeline(events, limit=20):
    """Render a bounded overview while preserving anchors and time span."""
    events = list(events or [])
    if not events:
        return (
            "<span class='muted'>No timeline "
            "events were recorded.</span>"
        )
    if len(events) <= limit:
        selected = events
    else:
        indexes = {
            0,
            len(events) - 1,
            *(
                index
                for index, event in enumerate(
                    events
                )
                if event.get("is_anchor")
            ),
        }
        slots = max(limit, 2)
        for position in range(slots):
            indexes.add(round(
                position
                * (len(events) - 1)
                / (slots - 1)
            ))
        ordered = sorted(indexes)
        if len(ordered) > limit:
            anchors = {
                index
                for index, event in enumerate(
                    events
                )
                if event.get("is_anchor")
            }
            required = {
                0,
                len(events) - 1,
                *anchors,
            }
            optional = [
                index
                for index in ordered
                if index not in required
            ]
            ordered = sorted(
                list(required)
                + optional[
                    :max(
                        limit
                        - len(required),
                        0,
                    )
                ]
            )
        selected = [
            events[index]
            for index in ordered
        ]
    note = (
        f"Showing {len(selected)} of "
        f"{len(events)} ordered events."
    )
    return (
        f"<div class='timeline-note'>{_esc(note)}</div>"
        + _render_timeline(selected)
    )


def _render_detections(detections):

    if not detections:
        return (
            "<i>No rules matched.</i>"
        )

    out = []

    for d in detections:

        out.append(
            "<div>"
            f"<b>[{_esc(d.get('level'))}]"
            f"</b> "
            f"{_esc(d.get('title'))} "
            f"<i>({_esc(d.get('category'))})"
            f"</i>"
            "<br>"
            f"<small>Matched on "
            f"{_esc(d.get('group_labels'))}"
            f" (count "
            f"{_esc(d.get('group_count'))})"
            f"</small>"
            "</div>"
        )

    return "<br>".join(out)


def _render_pivots(pivots):

    if not pivots:
        return "<i>None found.</i>"

    out = []

    for k, values in pivots.items():
        out.append(
            f"<div><b>{_esc(k)}:</b> "
            + "".join(
                f"<span>{_esc(v)}</span>"
                for v in values
            )
            + "</div>"
        )

    return "".join(out)


def _render_log_groups(groups):

    if not groups:
        return "(none)"

    rows = []

    for g in groups[:15]:

        rows.append(
            f"<div>"
            f"<code>[{g.get('count')}]"
            f"</code> "
            f"{_esc(g.get('labels'))} "
            f"— {_esc(g.get('example_message'))}"
            f"</div>"
        )

    return "\n".join(rows)


def render(state, heatmap_ascii):

    # HTML is an export sink. Redact here as a final boundary even if a caller
    # accidentally passes unnormalized connector or reviewer data.
    state = redact_data(state or {})

    bctx = state.get(
        "business_context", {}
    ) or {}

    return _TEMPLATE.format(
        title=(
            f"[{state.get('incident_id', 'unknown')}]"
            f" postmortem"
        ),
        incident_id=_esc(
            state.get("incident_id")
        ),
        sev=_esc(
            state.get(
                "severity", "SEV?"
            )
        ),
        sev_reason=_esc(
            state.get(
                "severity_reason", ""
            )
        ),
        service=_esc(
            bctx.get("service")
        ),
        tier=_esc(
            bctx.get("tier")
        ),
        owner=_esc(
            bctx.get("owner")
        ),
        runbook=_esc(
            bctx.get("runbook")
            or "-"
        ),
        postmortem=_md_to_html(
            state.get(
                "postmortem_draft", ""
            )
        ),
        rca=_md_to_html(
            state.get(
                "rca_chain", ""
            )
        ),
        heatmap=_esc(heatmap_ascii),
        anchor=_esc(
            json.dumps(
                state.get(
                    "anchor_event"
                ),
                indent=2,
                default=str
            )
        ),
        timeline_rows=(
            _render_timeline(
                state.get(
                    "timeline", []
                )
            )
        ),
        detections=(
            _render_detections(
                state.get(
                    "detections", []
                )
            )
        ),
        pivots=_render_pivots(
            state.get(
                "pivots", {}
            )
        ),
        log_groups=(
            _render_log_groups(
                state.get(
                    "log_groups", []
                )
            )
        ),
        interpretation=_md_to_html(
            state.get(
                "interpretation", ""
            )
        )
    )


def _review_top_detection(state):
    detections = state.get(
        "detections", []
    ) or []
    if not detections:
        return {}, "no rule matched", "-"
    det = detections[0]
    return (
        det,
        det.get("title") or det.get("id") or "unknown",
        det.get("category") or "-"
    )


def _review_top_group(state):
    groups = state.get(
        "log_groups", []
    ) or []
    if not groups:
        return "none"
    group = groups[0]
    return (
        f"{group.get('labels')} "
        f"count={group.get('count')} "
        f"first={group.get('first_seen')}"
    )


def _review_top_deploy(state):
    deploys = state.get(
        "deploys", []
    ) or []
    if not deploys:
        return "none in window"
    deploy = deploys[0]
    return (
        f"{deploy.get('commit')} "
        f"at {deploy.get('time')} "
        f"({deploy.get('environment') or deploy.get('service')})"
    )


def _review_metric_summary(state):
    metrics = state.get(
        "metrics", []
    ) or []
    if not metrics:
        return "none"
    return ", ".join(
        f"{m.get('metric')}={m.get('value')}"
        for m in metrics[:5]
    )


def _review_pivot_summary(state):
    pivots = state.get(
        "pivots", {}
    ) or {}
    if not pivots:
        return "none"
    rows = []
    for key, values in pivots.items():
        rows.append(
            f"{key}="
            + ",".join(
                str(v)
                for v in values[:3]
            )
        )
    return "; ".join(rows)


def _review_anchor(state):
    anchor = state.get(
        "anchor_event"
    ) or {}
    if not anchor:
        return "none"
    return (
        f"{anchor.get('timestamp')} "
        f"{anchor.get('labels')} "
        f"{anchor.get('example_message')}"
    )


def _review_known_gap(state):
    raw_count = state.get(
        "raw_log_count", 0
    )
    tool_note = (
        f"{raw_count} raw logs omitted from prompt; "
        "use search_logs before approval if sample evidence looks thin."
    )
    suppressed = state.get(
        "suppressed_groups", []
    ) or []
    if suppressed:
        return (
            tool_note
            + f" {len(suppressed)} suppressed group(s) not in LLM context."
        )
    return tool_note


def _review_semantic_correlation(state):
    report = state.get(
        "semantic_correlation", {}
    ) or {}

    if not report:
        return "none"

    return json.dumps(
        report,
        indent=2,
        default=str
    )


def _review_semantic_tool_trace(state):
    trace = state.get(
        "semantic_correlation_tool_trace",
        []
    ) or []

    if not trace:
        searches = (
            state.get(
                "semantic_correlation",
                {}
            )
            or {}
        ).get("searches_performed", [])
        trace = searches or []

    if not trace:
        return "none"

    return json.dumps(
        trace,
        indent=2,
        default=str
    )


def _review_evidence_coverage(state):
    sources = state.get(
        "source_status", {}
    ) or {}
    cards = []
    for name, value in sorted(
        sources.items()
    ):
        status = (
            value
            if isinstance(value, dict)
            else {}
        )
        source_provenance = (
            status.get(
                "provenance", {}
            )
            or {}
        )
        quality = (
            status.get(
                "data_quality", {}
            )
            or {}
        )
        query_details = (
            source_provenance.get(
                "query_specification", {}
            )
            or {}
        )
        cards.append(
            '<section class="source-card">'
            f"<h3>{_esc(name)}</h3>"
            "<dl>"
            "<dt>Status</dt>"
            f"<dd>{_esc(status.get('status', 'unknown'))}</dd>"
            "<dt>Schema</dt>"
            f"<dd>{_esc(source_provenance.get('source_schema_id', 'unknown'))}</dd>"
            "<dt>Query ID</dt>"
            f"<dd><code>{_esc(source_provenance.get('query_id', 'unknown'))}</code></dd>"
            "<dt>Matched</dt>"
            f"<dd>{_esc(source_provenance.get('result_count', 0))}</dd>"
            "<dt>Fetched → usable</dt>"
            f"<dd>{_esc(source_provenance.get('fetched_count', 0))}"
            " → "
            f"{_esc(source_provenance.get('reduced_count', 0))}</dd>"
            "<dt>Truncated</dt>"
            f"<dd>{_esc(source_provenance.get('truncated', False))}</dd>"
            "<dt>Quarantined</dt>"
            f"<dd>{_esc(quality.get('quarantined_records', 0))}</dd>"
            "<dt>Duplicates</dt>"
            f"<dd>{_esc(quality.get('duplicate_records', 0))}</dd>"
            "<dt>Freshness</dt>"
            f"<dd>{_esc(quality.get('freshness_seconds'))} seconds</dd>"
            "</dl>"
            "<details>"
            "<summary>Sanitized replay specification</summary>"
            "<pre>"
            + _esc(
                json.dumps(
                    query_details,
                    indent=2,
                    default=str,
                )
            )
            + "</pre></details>"
            "</section>"
        )
    if not cards:
        cards.append(
            '<section class="source-card">'
            "<h3>No source status</h3>"
            "<p class=\"muted\">No connector "
            "coverage was recorded.</p>"
            "</section>"
        )
    window = _esc(
        json.dumps(
            state.get(
                "incident_window", {}
            ),
            sort_keys=True,
            default=str,
        )
    )
    return (
        '<p class="muted">Incident window: '
        + window
        + "</p>"
        + '<div class="source-grid">'
        + "".join(cards)
        + "</div>"
    )


def _review_unknowns(state):
    report = state.get("semantic_correlation", {}) or {}
    missing = report.get("missing_evidence", []) or []
    validation = report.get("validation", {}) or {}
    source_status = state.get("source_status", {}) or {}
    failures = [
        f"{name}: {value.get('status')} {value.get('error', '')}"
        for name, value in source_status.items()
        if isinstance(value, dict)
        and value.get("status") != "ok"
    ]
    rows = [*missing, *failures, *validation.get("warnings", [])]
    return "\n".join(rows) if rows else "No known evidence gaps."


def _review_interpretation_quality(state):
    return json.dumps(
        state.get("interpretation_quality", {}),
        indent=2,
        default=str,
    )


def _review_verification_commands(state):
    bctx = state.get(
        "business_context", {}
    ) or {}
    service = (
        bctx.get("service")
        or state.get("alert", {}).get("service")
        or "service"
    )
    pivots = state.get(
        "pivots", {}
    ) or {}
    trace = (
        pivots.get("trace_id", [None])[0]
        if pivots.get("trace_id")
        else None
    )
    deploys = state.get(
        "deploys", []
    ) or []
    commit = (
        deploys[0].get("commit")
        if deploys
        else None
    )

    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    candidates = assessment.get(
        "candidates", []
    ) or []
    patterns = assessment.get(
        "observation_patterns", []
    ) or []
    commands = []
    used_event_ids = set()

    if candidates:
        event_ids = (
            candidates[0].get(
                "event_ids", []
            )
            or []
        )
        if event_ids:
            event_id = event_ids[0]
            used_event_ids.add(
                event_id
            )
            commands.append((
                "Inspect leading candidate evidence",
                "get_log_context("
                f"event_id='{event_id}')",
            ))

    for pattern in patterns[:2]:
        representatives = (
            pattern.get(
                "representative_evidence",
                [],
            )
            or []
        )
        event_id = next(
            (
                item.get("event_id")
                for item in representatives
                if (
                    item.get("event_id")
                    and item.get(
                        "event_id"
                    )
                    not in used_event_ids
                )
            ),
            None,
        )
        if not event_id:
            continue
        used_event_ids.add(
            event_id
        )
        commands.append((
            "Inspect observation-pattern evidence",
            "get_log_context("
            f"event_id='{event_id}')",
        ))

    if trace:
        commands.append((
            "Trace one affected request",
            f"search_logs(pattern='{trace}', service='{service}')"
        ))
    if commit:
        commands.append((
            "Validate deploy correlation",
            f"check deploy {commit} and compare first error timestamp"
        ))
    if not commands:
        commands.append((
            "Collect discriminating evidence",
            "search_logs("
            f"service='{service}', "
            "level='error')",
        ))

    return "".join(
        "<div>"
        f"<b>{_esc(title)}</b>"
        f"<code class='cmd'>{_esc(cmd)}</code>"
        "</div>"
        for title, cmd in commands
    )


def _review_feedback_examples():
    return (
        "Reject examples:\n"
        "- Hypothesis 1 cites a repeated symptom but ignores the direct fault event; rerank using the cited event IDs.\n"
        "- Missing evidence: verify whether the dependency error is a cause or downstream symptom.\n"
        "- Confidence too high: no metric or log sample directly supports the proposed mechanism.\n"
        "- Next action unsafe: a destructive change is suggested without causal evidence or approval."
    )


def _review_investigation_outcome(state):
    loop = (
        state.get("investigation_loop")
        or (
            state.get("investigation_budget", {})
            or {}
        ).get("expansion_loop")
        or {}
    )
    revisions = (
        state.get("investigation_revisions", [])
        or []
    )
    if not loop:
        return (
            "<span class='muted'>No targeted expansion "
            "round was recorded.</span>"
        )
    latest = revisions[-1] if revisions else {}
    query_ids = latest.get("query_ids", []) or []
    status = (
        "continue"
        if loop.get("continue_expansion")
        else "stopped"
    )
    rows = [
        ("Status", status),
        (
            "Rounds",
            f"{loop.get('round', 0)} / {loop.get('max_rounds', '?')}",
        ),
        (
            "Scoped services",
            (
                f"{len((state.get('scope_expansion', {}) or {}).get('services', []) or [])}"
                f" / {loop.get('max_services', '?')}"
            ),
        ),
        (
            "Retained tool bytes",
            (
                f"{loop.get('used_result_bytes', 0)}"
                f" / {loop.get('max_result_bytes', '?')}"
            ),
        ),
        ("Stop reason", loop.get("stop_reason") or "not stopped"),
        ("Details", loop.get("stop_details") or "none"),
        ("Recorded revisions", len(revisions)),
        (
            "Latest query IDs",
            ", ".join(str(item) for item in query_ids) or "none",
        ),
    ]
    return (
        "<div class='kv'>"
        + "".join(
            f"<b>{_esc(label)}</b><span>{_esc(value)}</span>"
            for label, value in rows
        )
        + "</div>"
    )


def _review_analysis_state(state):
    hypothesis_count = (
        _review_hypothesis_count(
            state
        )
    )
    structured = dict(
        state.get(
            "interpretation_structured",
            {},
        )
        or {}
    )
    if hypothesis_count and not structured.get(
        "hypotheses"
    ):
        structured["hypotheses"] = [
            {"rank": rank}
            for rank in range(
                1,
                hypothesis_count + 1,
            )
        ]
    return analysis_review_state(
        state,
        structured,
    )


def _review_hypothesis_count(state):
    structured = state.get("interpretation_structured", {}) or {}
    hypotheses = structured.get("hypotheses")
    if isinstance(hypotheses, list):
        return min(len(hypotheses), 3)

    interpretation = str(state.get("interpretation", "") or "")
    ranks = {
        int(match)
        for match in re.findall(
            r"(?im)^\s*#{1,4}\s+hypothesis\s+([1-3])\s*[:.-]",
            interpretation,
        )
    }
    return len(ranks)


def _review_analysis_status(state):
    status = _review_analysis_state(state)
    if status["unavailable"]:
        return (
            '<p class="risk"><b>Agent analysis unavailable.</b> '
            "Approval is disabled until the LLM produces hypotheses.</p>"
        )
    if status["inconclusive"]:
        return (
            '<p class="risk"><b>AI abstained: inconclusive evidence.</b> '
            "Approval is disabled until the analysis produces hypotheses.</p>"
        )
    if (
        status["can_approve"]
        and status[
            "provider_degraded"
        ]
    ):
        return (
            '<p class="risk"><b>Model provider unavailable.</b> '
            "The displayed deterministic interpretation and claim grounding "
            "passed. Review the limitation before approving.</p>"
        )
    if not status["can_approve"]:
        return (
            '<p class="risk"><b>Analysis is not approvable.</b> '
            "Interpretation quality and claim grounding must both pass for "
            "this exact revision.</p>"
        )
    return ""


def _review_decision_controls(state):
    status = _review_analysis_state(state)
    reject_label = (
        "Reject &amp; re-interpret"
        if status["can_approve"]
        else "Retry agent analysis"
    )
    reject_class = "panel reject" if status["can_approve"] else "panel reject only"
    approve = ""
    if status["can_approve"]:
        hypothesis_options = "".join(
            f'<option value="{rank}">{rank}</option>'
            for rank in status[
                "approvable_ranks"
            ]
        )
        approve = (
            '<div class="panel approve">'
            "<h3>Approve</h3>"
            "<label>Hypothesis "
            '<select id="chosenHypothesis">'
            + hypothesis_options
            + "</select></label>"
            '<button onclick="approveReview()">Approve &amp; continue</button>'
            "<p class=\"muted\">Use when the cause, evidence, and next action "
            "are good enough for RCA.</p></div>"
        )
    return (
        approve
        + f'<div class="{reject_class}">'
        + ("<h3>Reject</h3>" if status["can_approve"] else "<h3>Retry analysis</h3>")
        + '<textarea id="reviewFeedback" placeholder="What is wrong or missing?">'
        "</textarea>"
        '<button class="reject-btn" onclick="rejectReview()">'
        + reject_label
        + "</button>"
        '<button onclick="requestMoreEvidence()">Request more evidence</button>'
        '<p class="muted">Include exact missing evidence or reviewer context.</p>'
        "</div>"
    )


def render_review(state):

    # The review page exposes feedback, tool traces and connector metadata.
    # Apply the same final export boundary as the postmortem report.
    state = redact_data(state or {})

    incident_id = state.get(
        "incident_id", "unknown"
    )
    bctx = state.get(
        "business_context", {}
    ) or {}
    top_det, top_detection, top_category = (
        _review_top_detection(state)
    )

    return _REVIEW_TEMPLATE.format(
        title=(
            f"[{_esc(incident_id)}] "
            "review"
        ),
        incident_id_json=json.dumps(
            incident_id
        ),
        api_base_json=json.dumps(
            REVIEW_API_BASE
        ),
        attempt=_esc(
            state.get(
                "interpretation_attempts",
                1
            )
        ),
        analysis_status=(
            _review_analysis_status(state)
        ),
        severity=_esc(
            state.get("severity", "unknown")
        ),
        severity_reason=_esc(
            state.get("severity_reason", "")
        ),
        service=_esc(
            bctx.get("service", "unknown")
        ),
        owner=_esc(
            bctx.get("owner", "unknown")
        ),
        tier=_esc(
            bctx.get("tier", "?")
        ),
        top_detection=_esc(
            top_detection
        ),
        top_category=_esc(
            top_category
        ),
        raw_log_count=_esc(
            state.get("raw_log_count", 0)
        ),
        log_group_count=_esc(
            len(state.get("log_groups", []) or [])
        ),
        detection_count=_esc(
            len(state.get("detections", []) or [])
        ),
        anchor=_esc(
            _review_anchor(state)
        ),
        top_group=_esc(
            _review_top_group(state)
        ),
        top_deploy=_esc(
            _review_top_deploy(state)
        ),
        metric_summary=_esc(
            _review_metric_summary(state)
        ),
        pivot_summary=_esc(
            _review_pivot_summary(state)
        ),
        known_gap=_esc(
            _review_known_gap(state)
        ),
        review_timeline=(
            _review_timeline(
                state.get(
                    "timeline", []
                )
            )
        ),
        semantic_correlation=_esc(
            _review_semantic_correlation(
                state
            )
        ),
        semantic_tool_trace=_esc(
            _review_semantic_tool_trace(
                state
            )
        ),
        evidence_coverage=(
            _review_evidence_coverage(
                state
            )
        ),
        unknowns=_esc(
            _review_unknowns(state)
        ),
        deterministic_assessment=_esc(
            json.dumps(
                state.get(
                    "deterministic_assessment", {}
                ),
                indent=2,
                default=str,
            )
        ),
        investigation_outcome=(
            _review_investigation_outcome(state)
        ),
        investigation_budget=_esc(
            json.dumps(
                state.get("investigation_budget", {}),
                indent=2,
                default=str,
            )
        ),
        model_usage_and_deadline=_esc(
            json.dumps(
                {
                    "analysis_deadline":
                    state.get("analysis_deadline", {}),
                    "model_usage_ledger":
                    state.get("model_usage_ledger", {}),
                },
                indent=2,
                default=str,
            )
        ),
        interpretation_quality=_esc(
            _review_interpretation_quality(state)
        ),
        claim_grounding=_esc(
            json.dumps(
                state.get("claim_grounding", {}),
                indent=2,
                default=str,
            )
        ),
        verification_commands=(
            _review_verification_commands(state)
        ),
        decision_controls=(
            _review_decision_controls(state)
        ),
        approve_command=_esc(
            "{'status': 'approved', "
            "'chosen_hypothesis': 1}"
        ),
        reject_command=_esc(
            "{'status': 'rejected', "
            "'feedback': 'explain what is wrong'}"
        ),
        feedback_examples=_esc(
            _review_feedback_examples()
        ),
        interpretation=_md_to_html(
            state.get(
                "interpretation", ""
            )
        ),
        evidence_pack=_esc(
            state.get(
                "evidence_pack", ""
            )
        ),
        metrics=_esc(
            json.dumps(
                state.get("metrics", [])[:5],
                indent=2,
                default=str
            )
        ),
        deploys=_esc(
            json.dumps(
                state.get("deploys", [])[:3],
                indent=2,
                default=str
            )
        )
    )
