from collections.abc import Sequence


def response_completion(messages: Sequence[str], required: Sequence[str]) -> bool:
    text = " ".join(messages).casefold()
    return all(fragment.casefold() in text for fragment in required)
