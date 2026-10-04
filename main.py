from rich.console import Console
from ceo_ai import ceo_ai

console = Console()

console.print("""
[bold cyan]
████████████████████████████████
 AI-CEO AUTONOMOUS DEV PLATFORM
 Multi-Agent Software Company
████████████████████████████████
[/bold cyan]
""")

idea = input("Enter project idea: ")

ceo_ai(idea)