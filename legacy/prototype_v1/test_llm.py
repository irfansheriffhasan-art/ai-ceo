import ollama

response = ollama.chat(
    model="llama3",
    messages=[{"role":"user","content":"say hello"}]
)

print(response)