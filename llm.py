import ollama

def generate_website_code(idea):

    prompt = f"""
You are a senior frontend developer.

Create a small web project.

Idea:
{idea}

Output format:

HTML:
(index.html)

CSS:
(style.css)

JS:
(script.js)

No explanations.
"""

    response = ollama.chat(
        model="llama3",
        messages=[{"role":"user","content":prompt}]
    )

    return response["message"]["content"]