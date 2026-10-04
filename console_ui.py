from rich.console import Console
from rich.progress import track
import time

console = Console()

def ai_process(title, duration=1):

    console.print(f"\n[bold cyan]{title}[/bold cyan]")

    start = time.time()

    for _ in track(range(100), description="Processing"):
        time.sleep(duration/100)

    end = time.time()

    console.print(f"[green]Completed in {round(end-start,2)} seconds[/green]")