from utils.llm_context import (
    build_decision_brief,
    build_investigation_budget,
    build_policy_profiles,
)


def build_llm_context(state):
    budget = build_investigation_budget(state)
    return {
        "investigation_budget": budget,
        "decision_brief": build_decision_brief(state, budget),
        "skill_policy_profiles": build_policy_profiles(state),
    }
