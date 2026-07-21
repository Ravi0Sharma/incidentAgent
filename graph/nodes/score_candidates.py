from utils.candidate_scoring import score_candidates as build_assessment


def score_candidates(state):
    return {
        "deterministic_assessment": build_assessment(state)
    }
