from utils import safe_greet

def greet(name: str, age: int) -> str:
    if age < 0:
        raise ValueError("Age cannot be negative")
    
    return f"Hello {name}, you are {age} years old."

def main() -> None:
    try:
        print(greet(safe_greet(" commander Kirk"), 1))
    except ValueError as err:
        print (f"ERROR: {err}")

if __name__=="__main__":
    main()