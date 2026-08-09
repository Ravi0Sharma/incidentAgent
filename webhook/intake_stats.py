"""Process-local intake counters until production metrics are introduced."""

from collections import Counter

from utils.metrics import increment


_REJECTIONS = Counter()


def record_rejection(reason):
    _REJECTIONS[str(reason)] += 1
    increment("alerts", outcome="rejected", reason=str(reason))


def rejection_count(reason):
    return _REJECTIONS[str(reason)]


def reset_for_tests():
    _REJECTIONS.clear()
