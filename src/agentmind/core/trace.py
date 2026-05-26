import uuid


def generate_trace_id() -> str:
    return f"tr-{uuid.uuid4().hex[:16]}"
