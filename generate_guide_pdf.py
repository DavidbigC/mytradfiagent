import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tools.output import generate_pdf

async def main():
    # Read the Chinese user guide
    guide_path = "/Users/davidc/.gemini/antigravity/brain/77180199-97de-464b-8d7a-a2ecbf335223/user_guide_cn.md"
    try:
        with open(guide_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Could not find guide at {guide_path}")
        return

    # Generate PDF
    print("Generating PDF...")
    result = await generate_pdf("金融研究智能体使用指南", content)
    print(f"PDF Generated: {result['file']}")

if __name__ == "__main__":
    asyncio.run(main())
