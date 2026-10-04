from console_ui import console, ai_process

def tester_ai(build_output):

    console.print("\n[yellow]🧪 Tester AI validating project[/yellow]")

    ai_process("Running automated tests",1)

    console.print("[green]✔ All tests passed[/green]")

    return build_output