def normalize_name(name: str) -> str:
    return name.strip().title()

def safe_greet(name: str) -> str:
    clean_name = normalize_name(name)
    return clean_name