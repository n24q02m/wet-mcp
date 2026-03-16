from wet_mcp.security import wrap_external_content

print("NORMAL:")
print(repr(wrap_external_content("my_tool", "some content here")))

print("\nERROR:")
print(repr(wrap_external_content("my_tool", "Error: failed to connect")))
