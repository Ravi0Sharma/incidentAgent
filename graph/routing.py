def review_router(state):

    if (
        state["review_status"]
        == "approved"
    ):
        return "deep_rca"

    return "reinvestigate_feedback"
