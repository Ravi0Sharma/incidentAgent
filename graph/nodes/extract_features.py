from utils.incident_features import build_features


def extract_features(state):
    return {
        "incident_features": build_features(state)
    }
