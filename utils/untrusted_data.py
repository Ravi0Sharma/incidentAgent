"""Safely delimit externally supplied text before it enters an LLM prompt."""

import json

from utils.redaction import redact_data


def delimit(value, source):
    """Serialize evidence as data, not instructions.

    Delimiters are intentionally plain text: they work with every
    OpenAI-compatible model and make the handling rule visible in prompt
    snapshots and tests.  The caller's policy belongs outside this block.
    """
    payload = json.dumps(
        redact_data(value),
        ensure_ascii=False,
        default=str,
        sort_keys=True,
    )
    # A payload may contain our literal closing tag. Escape angle brackets in
    # the JSON representation so untrusted text cannot visually terminate the
    # data block or create a second policy-looking block in the prompt.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e")
    encoded_source = json.dumps(str(source)).replace(
        "<", "\\u003c"
    ).replace(">", "\\u003e")
    return (
        "<untrusted-evidence source=" + encoded_source + ">\n"
        + payload
        + "\n</untrusted-evidence>"
    )
