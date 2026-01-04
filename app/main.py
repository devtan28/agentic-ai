from data_utils import has_valid_age

def average_age(people: list[dict]) -> float:
    total_age = 0
    count = 0

    for person in people:
        if not has_valid_age(person):
            continue
        total_age += person["age"]
        count += 1
    if count == 0:
        raise ValueError("No valid ages provided")
    
    return total_age / count


def main() -> None:
    team = [
        {"name": " Alice", "age": 34},
        {"name": "Bob", "age": 44},
        {"name": "Charlie", "age": 23},
    ]

    age = average_age(team)
    print (f"Average Age: {age}")

if __name__ == "__main__":
    main()
