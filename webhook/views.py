import html

from utils.render_safety import bounded_text

from fastapi.responses import (
    HTMLResponse
)

from webhook.interpretation import (
    split_hypothesis_body
)


STYLE = """
body{font-family:-apple-system,
BlinkMacSystemFont,'Segoe UI',
Roboto,sans-serif;margin:0;
background:#0b0d13;color:#e6e6e6;
line-height:1.5}
.wrap{max-width:1100px;margin:0 auto;
padding:32px 24px}
a{color:#7aa2ff;text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:26px;font-weight:700;
letter-spacing:-0.01em;margin:0
0 4px}
h2{font-size:18px;font-weight:600;
margin:0 0 12px;color:#c9d1de}
h3{font-size:14px;font-weight:600;
text-transform:uppercase;
letter-spacing:0.08em;
color:#8a93a3;margin:0 0 12px}
h4{font-size:13px;font-weight:700;
color:#c9d1de;margin:14px 0 6px;
text-transform:uppercase;
letter-spacing:0.06em}
table{width:100%;border-collapse:
collapse}
th,td{text-align:left;padding:12px
14px;border-bottom:1px solid #1d222e}
th{font-size:12px;text-transform:
uppercase;letter-spacing:0.08em;
color:#8a93a3;font-weight:600}
tbody tr:hover{background:#12151d}
.card{background:#131722;border:1px
solid #1d222e;border-radius:12px;
padding:20px 22px;margin:18px 0}
.card.tldr{background:linear-gradient
(180deg,#1a2035,#131722);
border-left:4px solid #7aa2ff}
.card.tldr .body{font-size:16px;
color:#e6e6e6}
.hyp{background:#131722;border:1px
solid #1d222e;border-radius:12px;
padding:0;margin:18px 0;overflow:
hidden}
.hyp .head{display:flex;align-items:
center;gap:14px;padding:16px 22px;
background:#151a26;border-bottom:1px
solid #1d222e}
.hyp .num{background:#2b3348;
color:#7aa2ff;font-weight:700;
width:36px;height:36px;border-radius:
50%;display:flex;align-items:center;
justify-content:center;font-size:16px;
flex-shrink:0}
.hyp .title{font-size:17px;font-weight:
600;color:#f0f2f7;flex:1}
.badge{font-size:11px;font-weight:700;
text-transform:uppercase;
letter-spacing:0.08em;padding:5px 10px;
border-radius:999px;white-space:nowrap}
.badge.high{background:rgba(255,107,
107,0.15);color:#ff8888;border:1px
solid rgba(255,107,107,0.3)}
.badge.medium{background:rgba(255,212,
59,0.15);color:#ffd45b;border:1px
solid rgba(255,212,59,0.3)}
.badge.low{background:rgba(138,147,
163,0.15);color:#a8b1c2;border:1px
solid rgba(138,147,163,0.3)}
.badge.unknown{background:rgba(138,
147,163,0.10);color:#8a93a3;border:
1px solid rgba(138,147,163,0.25)}
.pct-bar{height:4px;background:
#1c2230;overflow:hidden}
.pct-bar .pct-fill{height:100%;
transition:width 0.4s ease}
.pct-bar.high .pct-fill{background:
linear-gradient(90deg,#ff6b6b,
#ff8888)}
.pct-bar.medium .pct-fill{background:
linear-gradient(90deg,#ffd45b,
#ffe08a)}
.pct-bar.low .pct-fill{background:
linear-gradient(90deg,#7fdc8f,
#a5e6ae)}
.pct-bar.unknown .pct-fill{background:
#3a4152}
.hyp .body{padding:8px 22px 18px}
.hyp .body p{margin:6px 0}
.hyp .body ul,.hyp .body ol{margin:
6px 0;padding-left:22px}
.hyp .body li{margin:3px 0}
.hyp .body code{background:#1c2230;
padding:1px 6px;border-radius:4px;
font-family:ui-monospace,SFMono-Regular,
Menlo,monospace;font-size:0.9em;
color:#a5d6ff}
.sub{margin:12px 0 0;padding:12px
14px;border-radius:8px;background:
#0f131c;border-left:3px solid
#2a2f3a}
.sub.evidence{border-left-color:
#7aa2ff}
.sub.correlation{border-left-color:
#7fdc8f}
.sub.weaknesses{border-left-color:
#ffd45b}
.sub.other{border-left-color:#3a4152;
background:transparent;border-left:0;
padding:0 0 8px}
.sub.empty{opacity:0.55}
.sub-label{font-size:11px;font-weight:
700;text-transform:uppercase;
letter-spacing:0.09em;color:#8a93a3;
margin-bottom:6px}
.sub.evidence .sub-label{color:
#7aa2ff}
.sub.correlation .sub-label{color:
#7fdc8f}
.sub.weaknesses .sub-label{color:
#ffd45b}
.sub-body{color:#d5dae4;font-size:
14px;line-height:1.55}
.sub-body p{margin:4px 0}
.sub-body ul,.sub-body ol{margin:
4px 0;padding-left:20px}
.sub-body li{margin:2px 0}
.sub-body code{background:#1c2230;
padding:1px 6px;border-radius:4px;
font-family:ui-monospace,SFMono-Regular,
Menlo,monospace;font-size:0.9em;
color:#a5d6ff}
.md p{margin:6px 0}
.md ul,.md ol{margin:6px 0;
padding-left:22px}
.md li{margin:3px 0}
.md code{background:#1c2230;padding:
1px 6px;border-radius:4px;font-family:
ui-monospace,SFMono-Regular,Menlo,
monospace;font-size:0.9em;color:
#a5d6ff}
button{background:#3b6fd8;color:#fff;
border:0;border-radius:8px;padding:
10px 18px;cursor:pointer;font-size:
14px;font-weight:600;transition:
background 0.15s}
button:hover{background:#4b7fe8}
button.reject{background:#a13a3a}
button.reject:hover{background:
#b64545}
select,textarea{background:#0b0d13;
color:#e6e6e6;border:1px solid
#2a2f3a;border-radius:8px;padding:
10px 12px;font-size:14px;font-family:
inherit}
textarea{width:100%;min-height:80px;
resize:vertical}
.row{display:flex;gap:12px;
align-items:center;flex-wrap:wrap}
.muted{color:#8a93a3;font-size:13px}
.sev{font-weight:600}
.sev-critical{color:#ff6b6b}
.sev-warning{color:#ffd45b}
.pill{display:inline-block;padding:
3px 10px;background:#1c2230;
border-radius:999px;font-size:12px;
color:#c9d1de;margin-right:6px}
.pill.agent-unavailable{background:#463c21;
color:#ffd45b}
.status-msg{margin-top:10px;font-size:
13px;color:#8a93a3;min-height:16px}
.status-msg.working{color:#ffd45b}
.status-msg.done{color:#7fdc8f}
#tl{background:#0f131c;border-radius:
8px;padding:6px}
.vis-item{background:#3b6fd8
!important;border-color:#3b6fd8
!important;color:#fff !important;
border-radius:4px !important}
.vis-item.deploys{background:
#7fdc8f !important;border-color:
#7fdc8f !important;color:#0b0d13
!important}
.vis-item.logs{background:#ff8888
!important;border-color:#ff8888
!important}
.vis-item.metrics{background:
#ffd45b !important;border-color:
#ffd45b !important;color:#0b0d13
!important}
.vis-label{color:#c9d1de !important}
.vis-time-axis .vis-text{color:
#8a93a3 !important}
.vis-panel{border-color:#1d222e
!important}
"""


def page(body):
    return HTMLResponse(
        "<!doctype html><html><head>"
        "<meta charset='utf-8'>"
        "<title>Incident Agent</title>"
        "<meta name='viewport' "
        "content='width=device-width,"
        "initial-scale=1'>"
        "<style>" + STYLE + "</style>"
        "<link href='https://unpkg.com"
        "/vis-timeline@7.7.3/styles"
        "/vis-timeline-graph2d.min.css'"
        " rel='stylesheet'>"
        "<script src='https://unpkg.com"
        "/vis-timeline@7.7.3/standalone"
        "/umd/vis-timeline-graph2d.min"
        ".js'></script>"
        "</head><body><div class='wrap'>"
        + body
        + "</div></body></html>"
    )


def _revision_id_list(value, limit=12):
    if not isinstance(value, list):
        return []
    return [str(item)[:255] for item in value if str(item).strip()][:limit]


def _evidence_change_block(label, values):
    ids = _revision_id_list(values)
    total = len(values) if isinstance(values, list) else 0
    if not ids:
        return ""
    suffix = (
        " <span class='muted'>(+"
        + str(total - len(ids))
        + " more)</span>"
        if total > len(ids)
        else ""
    )
    return (
        "<div class='sub evidence'><div class='sub-label'>"
        + html.escape(label)
        + "</div><div class='sub-body'>"
        + ", ".join(
            "<code>" + html.escape(value) + "</code>"
            for value in ids
        )
        + suffix
        + "</div></div>"
    )


def _candidate_change_summary(change):
    if not isinstance(change, dict):
        return ""
    identifier = str(change.get("candidate_id") or "unknown")[:255]
    before = change.get("before") if isinstance(change.get("before"), dict) else None
    after = change.get("after") if isinstance(change.get("after"), dict) else None
    if before is None and after is None:
        return ""
    details = []
    if before is None:
        details.append("added at rank " + str(after.get("rank") or "?"))
    elif after is None:
        details.append("removed (was rank " + str(before.get("rank") or "?") + ")")
    else:
        if before.get("rank") != after.get("rank"):
            details.append(
                "rank " + str(before.get("rank") or "?")
                + " → " + str(after.get("rank") or "?")
            )
        if before.get("confidence_label") != after.get("confidence_label"):
            details.append(
                "confidence " + str(before.get("confidence_label") or "unknown")
                + " → " + str(after.get("confidence_label") or "unknown")
            )
        if (
            before.get("score") is not None
            and after.get("score") is not None
            and before.get("score") != after.get("score")
        ):
            details.append(
                "uncalibrated score " + str(before.get("score"))
                + " → " + str(after.get("score"))
            )
        before_ids = set(_revision_id_list(before.get("event_ids"), 100))
        after_ids = set(_revision_id_list(after.get("event_ids"), 100))
        if after_ids - before_ids:
            added = sorted(after_ids - before_ids)
            details.append(
                "evidence +" + str(len(added))
                + " (" + ", ".join(added[:3]) + ")"
            )
        if before_ids - after_ids:
            removed = sorted(before_ids - after_ids)
            details.append(
                "evidence -" + str(len(removed))
                + " (" + ", ".join(removed[:3]) + ")"
            )
        if before.get("title") != after.get("title"):
            details.append("title updated")
    if not details:
        details.append("candidate details updated")
    return (
        "<li><code>" + html.escape(identifier) + "</code>: "
        + html.escape("; ".join(details))
        + "</li>"
    )


def render_revision_diff(diff):
    """Render a bounded, sanitized explanation of one analysis revision."""
    if (
        not isinstance(diff, dict)
        or diff.get("schema_version") != "analysis-revision-diff/v1"
    ):
        return ""
    revision = str(diff.get("revision") or "?")
    previous = diff.get("previous_revision")
    evidence = diff.get("evidence") if isinstance(diff.get("evidence"), dict) else {}
    blocks = "".join((
        _evidence_change_block("Evidence added", evidence.get("added", [])),
        _evidence_change_block("Evidence corrected", evidence.get("changed", [])),
        _evidence_change_block("Evidence removed", evidence.get("removed", [])),
    ))
    unchanged = len(evidence.get("unchanged", [])) if isinstance(
        evidence.get("unchanged"), list
    ) else 0
    candidate_rows = "".join(
        _candidate_change_summary(change)
        for change in (diff.get("candidate_changes", []) or [])[:20]
    )
    if candidate_rows:
        blocks += (
            "<div class='sub correlation'><div class='sub-label'>"
            "Candidate ranking changes</div><ul class='sub-body'>"
            + candidate_rows
            + "</ul></div>"
        )
    if previous is None:
        description = "Initial analysis revision; there is no prior review snapshot."
    else:
        description = (
            "Compared with analysis revision "
            + html.escape(str(previous))
            + ". "
            + str(unchanged)
            + " evidence IDs are unchanged."
        )
    if not blocks:
        blocks = "<p class='muted'>No review-relevant change was recorded.</p>"
    return (
        "<div class='card'><h3>What changed in analysis revision "
        + html.escape(revision)
        + "</h3><p class='muted'>"
        + description
        + "</p>"
        + blocks
        + "</div>"
    )

def _sub_section(
    label, content, kind
):
    """Render one Evidence/
    Correlation/Weaknesses block
    inside a hypothesis card."""
    if not content:
        return (
            "<div class='sub "
            + kind
            + " empty'>"
            "<div class='sub-label'>"
            + html.escape(label)
            + "</div>"
            "<div class='muted'>"
            "not provided</div>"
            "</div>"
        )
    return (
        "<div class='sub "
        + kind
        + "'>"
        "<div class='sub-label'>"
        + html.escape(label)
        + "</div>"
        "<pre class='sub-body'>"
        + html.escape(bounded_text(content, 50_000))
        + "</pre></div>"
    )


def render_hypothesis(h):
    conf = (
        (h.get("confidence") or "")
        .lower()
    )
    if conf not in (
        "high", "medium", "low"
    ):
        conf = "unknown"
    pct_raw = h.get("pct") or ""
    try:
        pct_num = int(pct_raw)
    except (ValueError, TypeError):
        pct_num = 0
    badge_text = (
        h.get("confidence")
        or "Unknown"
    )
    if pct_raw:
        badge_text = (
            badge_text
            + " \u00b7 "
            + pct_raw
            + "%"
        )
    num = h.get("num") or "?"
    title = html.escape(bounded_text(h.get("title") or "", 1_000))

    parts = split_hypothesis_body(
        h.get("body") or ""
    )

    other_html = ""
    if parts["other"]:
        other_html = (
            "<div class='sub other'>"
            "<pre class='sub-body'>"
            + html.escape(bounded_text(parts["other"], 50_000))
            + "</pre></div>"
        )

    pct_bar = ""
    if pct_num > 0:
        pct_bar = (
            "<div class='pct-bar "
            + conf
            + "'><div class='pct-fill'"
            " style='width:"
            + str(min(pct_num, 100))
            + "%'></div></div>"
        )

    return (
        "<div class='hyp' data-num='"
        + html.escape(num)
        + "'>"
        "<div class='head'>"
        "<div class='num'>"
        + html.escape(num)
        + "</div>"
        "<div class='title'>"
        + title
        + "</div>"
        "<span class='badge "
        + conf
        + "'>"
        + html.escape(badge_text)
        + "</span></div>"
        + pct_bar
        + "<div class='body'>"
        + other_html
        + _sub_section(
            "Evidence",
            parts["evidence"],
            "evidence"
        )
        + _sub_section(
            "Correlation",
            parts["correlation"],
            "correlation"
        )
        + _sub_section(
            "Weaknesses",
            parts["weaknesses"],
            "weaknesses"
        )
        + "</div></div>"
    )
