def generate_report(idea,project_name):

    report=f"""
AI CEO SYSTEM REPORT
--------------------

Idea:
{idea}

Generated Project:
{project_name}

Files:
index.html
style.css
script.js

Agents:
CEO AI
R&D AI
Builder AI
Tester AI
Fixer AI
"""

    path=f"generated_sites/{project_name}/{project_name}_report.txt"

    with open(path,"w") as f:
        f.write(report)

    print("AI project report generated")