# Prototype v1 (archived)

The original AI-CEO prototype, kept for reference. It is not used by the platform.

Why it was replaced (see the audit in the main README):
- `builder_ai.py` required literal `HTML:` / `CSS:` / `JS:` markers that models never emit, so every
  run silently fell back to a hardcoded "add two numbers" page (all of `generated_sites/` is that stub).
- `llm.py` hardcoded the `llama3` model and had no error handling.
- `tester_ai.py` / `fixer_ai.py` slept for a second and printed success without testing or fixing anything.
- `rd_ai.py` returned a hardcoded tech stack.

Run the new platform with `python main.py` from the project root.
