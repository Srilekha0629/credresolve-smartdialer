"""
CredResolve SmartDialer Server Entrypoint
Usage: python backend/run_server.py
"""
import uvicorn

if __name__ == "__main__":
    print("Starting CredResolve SmartDialer Backend on http://localhost:8000...")
    print("FastAPI Interactive Docs available at http://localhost:8000/docs")
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
