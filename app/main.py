from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root() -> dict:
    return {"message": "AGentic AI service is running"}

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
