import re


META_PATTERNS = [
    r"^\s*\*+\s*(Wait|Refining"
    r"|Self[- ]Correction|Check"
    r" word count|Ensure specific"
    r"|Verify \"?No preamble"
    r"|Word count check|Check"
    r" constraints|Under \d+ "
    r"words|Exactly this structure"
    r"|Let me (?:think|refine|"
    r"reconsider|check|verify)"
    r"|Actually|Hmm|Okay,? let"
    r").*$",
    r"^\s*[-*]\s*Check (?:word"
    r" count|constraints)\.?\s*$",
    r"^\s*[-*]\s*Ensure specific.*$",
    r"^\s*[-*]\s*Verify \"?No preamble.*$",
    r"^\s*\*Self[- ]Correction.*?\*\s*$",
    r"^\s*\*Check constraints:.*$",
    r"^\s*Wait,? (?:need to|let me|I need).*$",
    r"^\s*\(Wait,?.*\)\s*$",
    r"^\s*\*+\s*Word count.*$"
]

SECTION_LABELS = (
    "Evidence",
    "Correlation",
    "Weaknesses"
)

HYP_HEADER_RE = re.compile(
    r"(?im)^\s*(?:#{1,4}\s+)?"
    r"(?:\*+\s*)?"
    r"(?:Hypothesis|H)\s*"
    r"(\d)\s*"
    r"(?:\(([^)]+)\))?"
    r"\s*[:\.\-]\s*"
    r"(?:\*+\s*)?"
    r"(.+?)\s*(?:\*+)?\s*$"
)


def clean_meta(text):
    if not text:
        return ""

    kept = []
    for line in text.split("\n"):
        drop = any(
            re.match(pattern, line, re.IGNORECASE)
            for pattern in META_PATTERNS
        )
        if not drop:
            kept.append(line)

    result = "\n".join(kept)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def promote_sublabels(body):
    if not body:
        return ""

    for label in SECTION_LABELS:
        body = re.sub(
            rf"(?m)^\s*{label}\s*:\s*$",
            f"#### {label}",
            body
        )
        body = re.sub(
            rf"(?m)^\s*\*+\s*{label}\s*:\*+\s*$",
            f"#### {label}",
            body
        )
    return body


def parse_confidence(text):
    if not text:
        return None, None

    match = re.search(
        r"Confidence\s*[:\-\u2014]?"
        r"\s*(High|Medium|Low)"
        r"[^\d]{0,20}(\d{1,3})?",
        text,
        re.IGNORECASE
    )
    if not match:
        match = re.search(
            r"[\(\[]\s*(High|Medium|Low)"
            r"(?:\s+confidence)?"
            r"\s*[,;\-\u2014]?"
            r"\s*(?:~|approx\.?)?"
            r"\s*(\d{1,3})?\s*%?"
            r"\s*[\)\]]",
            text,
            re.IGNORECASE
        )
    if not match:
        match = re.search(
            r"\b(High|Medium|Low)\s+confidence"
            r"[^\d]{0,20}(\d{1,3})?",
            text,
            re.IGNORECASE
        )
    if not match:
        return None, None

    return match.group(1).capitalize(), match.group(2) or ""


def split_hypothesis_body(body):
    result = {
        "evidence": "",
        "correlation": "",
        "weaknesses": "",
        "other": ""
    }
    if not body:
        return result

    pattern = re.compile(
        r"(?im)^\s*(?:#{2,4}\s+|\*+\s*)?"
        r"(Evidence|Correlation|Weaknesses)"
        r"\s*[:\*]*\s*$"
    )
    matches = list(pattern.finditer(body))

    if not matches:
        result["other"] = body.strip()
        return result

    if matches[0].start() > 0:
        result["other"] = body[:matches[0].start()].strip()

    for index, match in enumerate(matches):
        label = match.group(1).lower()
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(body)
        )
        chunk = body[start:end].strip()
        chunk = re.sub(
            r"^-{3,}\s*$",
            "",
            chunk,
            flags=re.MULTILINE
        ).strip()
        result[label] = chunk

    return result


def score_hypothesis(hypothesis):
    title = (hypothesis.get("title") or "").strip()
    body = hypothesis.get("body") or ""
    score = 0

    if title and not re.match(r"^[\d\s%.,\-\u2014]+$", title):
        score += 50
    if len(title) > 15:
        score += 15
    if len(title) > 40:
        score += 10

    score += min(len(body), 800) // 20

    if any(
        label.lower() in body.lower()
        for label in SECTION_LABELS
    ):
        score += 30

    if hypothesis.get("confidence"):
        score += 10

    return score


def dedup_hypotheses(items):
    by_num = {}
    for item in items:
        number = item["num"]
        previous = by_num.get(number)
        if (
            previous is None
            or score_hypothesis(item) > score_hypothesis(previous)
        ):
            by_num[number] = item

    return [
        by_num[number]
        for number in sorted(by_num.keys())
    ]


def parse_interpretation(text):
    text = clean_meta(text or "")

    result = {
        "tldr": "",
        "hypotheses": [],
        "blast_radius": "",
        "next_steps": "",
        "raw": text
    }

    has_md_headers = bool(
        re.search(
            r"(?m)^\s*#{1,3}\s+"
            r"(?:Hypothesis|TL;DR|Blast|Suggested|Next)",
            text,
            re.IGNORECASE
        )
    )
    parts = re.split(r"(?m)^\s*#{1,3}\s+", text) if has_md_headers else []
    header_based_hyps = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        head, _, body = part.partition("\n")
        head = head.strip()
        body = body.strip()
        low = head.lower()

        if low.startswith("tl;dr") or low == "tldr":
            result["tldr"] = body
        elif re.match(r"^\**\s*hypothesis\s+\d", low):
            match = re.match(
                r"^\**\s*hypothesis\s+(\d+)\s*[:\.\-]?\s*(.*)",
                low
            )
            number = match.group(1) if match else ""
            title_raw = head.split(":", 1)[1] if ":" in head else head
            title_raw = re.sub(r"^[\*\s]+|[\*\s]+$", "", title_raw)
            level, pct = parse_confidence(body)
            cleaned = re.sub(
                r"(?m)^\s*Confidence\s*:.*$",
                "",
                body
            ).strip()
            cleaned = promote_sublabels(cleaned)
            cleaned = re.sub(
                r"^-{3,}\s*$",
                "",
                cleaned,
                flags=re.MULTILINE
            ).strip()
            header_based_hyps.append({
                "num": number,
                "title": title_raw.strip(),
                "confidence": level,
                "pct": pct,
                "body": cleaned
            })
        elif "blast" in low:
            result["blast_radius"] = body
        elif "next steps" in low or "suggested" in low:
            result["next_steps"] = body

    if header_based_hyps:
        result["hypotheses"] = dedup_hypotheses(header_based_hyps)
        return result

    inline_hyps = []
    matches = list(HYP_HEADER_RE.finditer(text))

    for index, match in enumerate(matches):
        number = match.group(1)
        paren = (match.group(2) or "").strip()
        title = match.group(3).strip()
        title = re.sub(r"[\*_\s]+$", "", title)
        title_for_conf = (
            f"({paren}) {title}"
            if paren
            else title
        )
        title = re.sub(
            r"\s*\([^)]*\b(?:High|Medium|Low)\b[^)]*\)\.?\s*$",
            "",
            title,
            flags=re.IGNORECASE
        ).strip(" .")
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        body = text[start:end].strip()
        level, pct = parse_confidence(title_for_conf + " " + body)
        cleaned = re.sub(
            r"(?m)^\s*Confidence\s*:.*$",
            "",
            body
        ).strip()
        cleaned = promote_sublabels(cleaned)
        cleaned = re.sub(
            r"^-{3,}\s*$",
            "",
            cleaned,
            flags=re.MULTILINE
        ).strip()
        inline_hyps.append({
            "num": number,
            "title": title,
            "confidence": level,
            "pct": pct,
            "body": cleaned
        })

    if inline_hyps:
        result["hypotheses"] = dedup_hypotheses(inline_hyps)

    return result
