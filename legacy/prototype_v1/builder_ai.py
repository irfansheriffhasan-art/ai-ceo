import os
import webbrowser
import re
from llm import generate_website_code
from console_ui import console, ai_process

def builder_ai(rd_output):

    idea = rd_output["idea"]

    console.print("\n[magenta]Builder AI generating project[/magenta]")

    ai_process("Generating code with AI",2)

    project_name = idea.lower()
    project_name = re.sub(r'[^a-z0-9 ]','',project_name)
    project_name = project_name.replace(" ","_")

    project_path = f"generated_sites/{project_name}"

    os.makedirs(project_path,exist_ok=True)

    code = generate_website_code(idea)

    if "HTML:" not in code:

        console.print("[red]AI failed, using fallback template[/red]")

        html = """<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="style.css">
</head>
<body>

<h1>AI Generated App</h1>

<input id="a">
<input id="b">

<button onclick="add()">Add</button>

<p id="result"></p>

<script src="script.js"></script>

</body>
</html>
"""

        css = """
body{
font-family:Arial;
background:#222;
color:white;
text-align:center;
padding:40px;
}
"""

        js = """
function add(){
let a = Number(document.getElementById("a").value)
let b = Number(document.getElementById("b").value)

document.getElementById("result").innerText = a + b
}
"""

    else:

        html = code.split("CSS:")[0].replace("HTML:","")
        css = code.split("CSS:")[1].split("JS:")[0]
        js = code.split("JS:")[1]

    open(project_path+"/index.html","w").write(html)
    open(project_path+"/style.css","w").write(css)
    open(project_path+"/script.js","w").write(js)

    console.print("[green]Website generated successfully[/green]")
    console.print(f"Project folder: {project_name}")

    webbrowser.open("file://" + os.path.abspath(project_path+"/index.html"))

    return {
        "project_name":project_name,
        "project_path":project_path
    }