from console_ui import console, ai_process

def rd_ai(idea):

    console.print("\n[blue]R&D AI analyzing project[/blue]")

    ai_process("Analyzing requirements",1)

    return {
        "idea": idea,
        "tech_stack": ["HTML","CSS","JavaScript"]
    }