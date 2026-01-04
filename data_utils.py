def has_valid_age(person: dict) -> bool:
    return "age" in person and isinstance(person["age"], int)
