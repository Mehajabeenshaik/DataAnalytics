"""demo.py — CLI demo for ai_agent.ask().

Lets you type natural-language questions and see the governed metric
layer's response in real time. Works with either Ollama or Gemini
(depending on LLM_PROVIDER / .env config).

Usage:
    python demo.py
    LLM_PROVIDER=gemini python demo.py
"""
import os
import sys

# Bootstrap JWT_SECRET_KEY from .env before any project import
from dotenv import load_dotenv
load_dotenv()

from ai_agent import ask
from llm_provider import get_provider
from config import LLM_PROVIDER


def run_demo():
    provider = get_provider()
    print(f"{'='*60}")
    print(f"  DataAnalytics — AI Agent CLI Demo")
    print(f"  Provider: {provider.provider_name()}")
    print(f"{'='*60}")
    print()
    print("Type a question in plain English (or 'quit' to exit).")
    print()
    print("Examples:")
    print("  - What is our total revenue?")
    print("  - How many orders have we received?")
    print("  - Show me revenue by region")
    print("  - What is the refund rate?")
    print("  - What's the weather today?  (should decline — no_match)")
    print()

    while True:
        try:
            question = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if not question:
            continue

        print()
        try:
            result = ask(question, provider)

            # Print the response
            if result["metric_used"] is None:
                print(f"🤔 {result['answer']}")
            else:
                print(f"✅ {result['answer']}")

            print(f"   Metric:    {result['metric_used']}")
            print(f"   Confidence: {result['confidence']}")
            if result.get("caveat"):
                print(f"   ⚠️  Caveat: {result['caveat']}")
            if result.get("filters_used"):
                print(f"   Filters:   {result['filters_used']}")
        except Exception as e:
            print(f"❌ Error: {e}")
        print()


if __name__ == "__main__":
    run_demo()