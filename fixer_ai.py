from console_ui import console, ai_process

def fixer_ai(test_output):

    console.print("\n[red]Fixer AI optimizing project[/red]")

    ai_process("Applying fixes",1)

    console.print("[green]Optimization complete[/green]")

    return test_output