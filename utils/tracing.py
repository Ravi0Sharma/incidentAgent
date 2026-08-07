import time


def traced(fn):

    def wrapper(state):

        start = time.time()

        result = fn(state)

        duration = (
            time.time() - start
        )

        state.setdefault(
            "execution_log",
            []
        ).append(
            {
                "node":
                fn.__name__,

                "duration":
                duration
            }
        )

        return result

    return wrapper
