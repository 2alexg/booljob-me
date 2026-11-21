from fastapi import FastAPI

app = FastAPI(title="Bool API")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
