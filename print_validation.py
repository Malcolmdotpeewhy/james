from james.evolution.expander import ToolSandbox

sandbox = ToolSandbox()
result = sandbox.validate_code_safety("def tool():\n    return {'msg': 'safe'}\n")
print(result)
