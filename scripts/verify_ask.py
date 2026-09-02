# scripts/verify_ask.py
"""Verification script for the Nemotron ask endpoint.
Runs a flow:
1. Create a session (demo API key).
2. Upload sample_sales_data.csv.
3. Ask a series of questions.
4. Print full JSON answers.
"""

import requests
from pathlib import Path
import json

BASE_URL = "http://127.0.0.1:8001"
API_KEY = "ak_demo_key_12345"

def create_session() -> str:
    resp = requests.post(f"{BASE_URL}/api/v1/session", headers={"X-API-Key": API_KEY})
    resp.raise_for_status()
    return resp.json()["session_id"]

def upload_file(session_id: str, file_path: Path):
    files = {"file": (file_path.name, open(file_path, "rb"), "text/csv")}
    data = {"session_id": session_id}
    resp = requests.post(
        f"{BASE_URL}/api/v1/upload",
        headers={"X-API-Key": API_KEY},
        files=files,
        data=data,
    )
    resp.raise_for_status()
    return resp.json()

def ask_question(session_id: str, question: str):
    payload = {"session_id": session_id, "question": question}
    resp = requests.post(
        f"{BASE_URL}/api/v1/ask",
        headers={"X-API-Key": API_KEY},
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()

def main():
    session_id = create_session()
    print("Session ID:", session_id)
    csv_path = Path(r"C:/Users/bharu/OneDrive/Desktop/f6/sample_sales_data.csv")
    upload_res = upload_file(session_id, csv_path)
    print('Upload response:', json.dumps(upload_res, indent=2, ensure_ascii=True))
    questions = [
        "Describe the data",
        "What is the total sales?",
        "What is the total revenue?",
        "Sales by region",
        "What is the weather in Paris?",
    ]
    for q in questions:
        ans = ask_question(session_id, q)
        print("---")
        print("Q:", q)
        print('Answer JSON:')
        print(json.dumps(ans, indent=2, ensure_ascii=True))

if __name__ == "__main__":
    main()
