import asyncio
import json
import logging
from agent import run_agent

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


async def main():
    print("Financial Research Agent (type 'quit' to exit, 'clear' to reset history)")
    print("-" * 60)

    history = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.lower() == "clear":
            history = []
            print("History cleared.")
            continue

        try:
            result = await run_agent(user_input, conversation_history=history)
        except Exception as e:
            print(f"\nError: {e}")
            continue

        history = result.get("history", [])

        print(f"\nAgent: {result['text']}")

        for f in result.get("files", []):
            print(f"  [File: {f}]")


if __name__ == "__main__":
    asyncio.run(main())
