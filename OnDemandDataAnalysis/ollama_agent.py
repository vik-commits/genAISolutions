"""
Ollama Agent - Retail Prompt Responder
Uses Mistral LLM via Ollama to respond to prompts and context
from a retailPrompt.txt file.
"""

import json
import sys
import os
import requests
from pathlib import Path


# ─── Configuration ────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = "http://localhost:11434"
MODEL = "mistral"
PROMPT_FILE = "retailPrompt.txt"


# ─── Ollama Client ────────────────────────────────────────────────────────────

def check_ollama_running() -> bool:
    """Check if Ollama server is running."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        return False


def check_model_available(model: str) -> bool:
    """Check if the specified model is pulled and available."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return any(m["name"].startswith(model) for m in models)
    except Exception:
        pass
    return False


def pull_model(model: str) -> None:
    """Pull the model if not already available."""
    print(f"⏳ Pulling model '{model}' from Ollama... (this may take a while)")
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/pull",
        json={"name": model},
        stream=True,
        timeout=300,
    )
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            status = data.get("status", "")
            if "pulling" in status or "verifying" in status or "success" in status:
                print(f"  {status}")
    print(f"✅ Model '{model}' is ready.\n")


def generate_response(prompt: str, context: str, model: str = MODEL) -> str:
    """
    Send a prompt + context to Ollama and stream back the response.
    Returns the full response text.
    """
    system_message = (
        "You are a knowledgeable retail assistant AI. "
        "Use the provided context to inform your response. "
        "Be helpful, concise, and accurate."
    )

    full_prompt = f"Context:\n{context}\n\nQuestion / Task:\n{prompt}" if context.strip() else prompt

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": full_prompt},
        ],
        "stream": True,
    }

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        stream=True,
        timeout=3000,
    )
    response.raise_for_status()

    full_response = ""
    print("\n🤖 Mistral Response:\n" + "─" * 50)
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            chunk = data.get("message", {}).get("content", "")
            print(chunk, end="", flush=True)
            full_response += chunk
            if data.get("done"):
                break

    print("\n" + "─" * 50)
    return full_response


# ─── Prompt File Parser ───────────────────────────────────────────────────────

def parse_prompt_file(filepath: str) -> tuple[str, str]:
    """
    Parse retailPrompt.txt for PROMPT and CONTEXT sections.

    Supported formats:
      1. Sections labeled with [PROMPT] and [CONTEXT] headers
      2. Sections labeled with PROMPT: and CONTEXT: prefixes
      3. Plain text (treated entirely as the prompt, no context)

    Returns:
        (prompt, context) tuple of strings.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: '{filepath}'")

    raw = path.read_text(encoding="utf-8").strip()

    if not raw:
        raise ValueError(f"Prompt file '{filepath}' is empty.")

    prompt = ""
    context = ""

    # Format 1: [PROMPT] / [CONTEXT] section headers
    if "[PROMPT]" in raw.upper() or "[CONTEXT]" in raw.upper():
        lines = raw.splitlines()
        current_section = None
        buffer: dict[str, list[str]] = {"prompt": [], "context": []}

        for line in lines:
            upper = line.strip().upper()
            if upper in ("[PROMPT]", "[ PROMPT ]"):
                current_section = "prompt"
            elif upper in ("[CONTEXT]", "[ CONTEXT ]"):
                current_section = "context"
            elif current_section:
                buffer[current_section].append(line)

        prompt = "\n".join(buffer["prompt"]).strip()
        context = "\n".join(buffer["context"]).strip()

    # Format 2: PROMPT: / CONTEXT: inline prefixes
    elif raw.upper().startswith("PROMPT:") or "CONTEXT:" in raw.upper():
        for line in raw.splitlines():
            if line.upper().startswith("PROMPT:"):
                prompt += line[len("PROMPT:"):].strip() + "\n"
            elif line.upper().startswith("CONTEXT:"):
                context += line[len("CONTEXT:"):].strip() + "\n"

        prompt = prompt.strip()
        context = context.strip()

    # Format 3: Plain text
    else:
        prompt = raw

    if not prompt:
        raise ValueError(
            "Could not extract a PROMPT from the file. "
            "Please add a [PROMPT] section or PROMPT: prefix."
        )

    return prompt, context


# ─── Main Agent ───────────────────────────────────────────────────────────────

def run_agent(prompt_file: str = PROMPT_FILE) -> None:
    print("=" * 60)
    print("  🛒  Retail Ollama Agent  |  Model: Mistral")
    print("=" * 60)

    # 1. Check Ollama is running
    if not check_ollama_running():
        print(
            "❌ Ollama is not running.\n"
            "   Start it with:  ollama serve\n"
            "   Then re-run this script."
        )
        sys.exit(1)
    print("✅ Ollama server detected.")

    # 2. Ensure model is available
    if not check_model_available(MODEL):
        pull_model(MODEL)
    else:
        print(f"✅ Model '{MODEL}' is available.\n")

    # 3. Parse the prompt file
    print(f"📄 Reading prompt file: '{prompt_file}'")
    try:
        prompt, context = parse_prompt_file(prompt_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"\n📝 Prompt:\n{prompt}")
    if context:
        print(f"\n📚 Context (excerpt):\n{context[:300]}{'...' if len(context) > 300 else ''}")

    # 4. Generate response
    generate_response(prompt, context)

    print("\n✅ Agent finished.")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Optionally accept a custom prompt file path as CLI argument
    file_arg = sys.argv[1] if len(sys.argv) > 1 else PROMPT_FILE
    run_agent(file_arg)
