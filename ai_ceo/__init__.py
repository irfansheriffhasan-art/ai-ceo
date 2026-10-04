"""AI-CEO: an autonomous multi-agent software company.

The package is organised in layers:

- ``config``        typed settings loaded from the environment / ``.env``
- ``llm``           provider-agnostic LLM client (Ollama, Anthropic, OpenAI, Mock)
- ``db`` / ``memory`` / ``events``   persistent state, project memory and the event bus
- ``workspace``     safe file access, git and code intelligence for generated projects
- ``verification``  static checks, browser tests, API tests and security scanning
- ``agents``        the AI company: CEO, planner, PM and specialist agents
- ``orchestrator``  task scheduling, retries, failure recovery and the dev loop
- ``api``           FastAPI backend for the command-center dashboard
"""

__version__ = "2.0.0"
