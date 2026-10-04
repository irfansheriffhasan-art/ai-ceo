from console_ui import console, ai_process
from rd_ai import rd_ai
from builder_ai import builder_ai
from tester_ai import tester_ai
from fixer_ai import fixer_ai
from report_generator import generate_report

def ceo_ai(idea):

    console.print("\n[bold green]CEO AI received request[/bold green]")
    console.print(f"Idea: {idea}")

    ai_process("CEO analyzing request",1)

    rd_output = rd_ai(idea)

    build_output = builder_ai(rd_output)

    test_output = tester_ai(build_output)

    fix_output = fixer_ai(test_output)

    project_name = build_output["project_name"]

    generate_report(idea, project_name)

    console.print("\n[bold green]Deployment Successful[/bold green]")