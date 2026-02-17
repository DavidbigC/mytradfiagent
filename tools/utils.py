def safe_value(v):
    """Convert pandas/numpy types to JSON-serializable Python types."""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        return v.item()
    return v
