from pathlib import Path

from graphgpt import compile_workflow

graph = compile_workflow(Path(__file__).with_name("server.yaml"))
