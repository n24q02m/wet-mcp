path = 'src/wet_mcp/db.py'
with open(path, 'r') as f:
    lines = f.readlines()

import_lines = []
other_lines = []
docstring_done = False
imports_done = False

for line in lines:
    if not docstring_done:
        other_lines.append(line)
        if '"""' in line and lines.index(line) > 0:
            docstring_done = True
        continue

    if not imports_done:
        if line.strip().startswith(('import ', 'from ')):
            import_lines.append(line)
        elif line.strip() == '' and (not import_lines or import_lines[-1].strip() == ''):
             # Keep empty lines within or after imports
             if import_lines:
                 import_lines.append(line)
             else:
                 other_lines.append(line)
        elif not line.strip():
             if import_lines:
                 import_lines.append(line)
             else:
                 other_lines.append(line)
        else:
            imports_done = True
            other_lines.append(line)
    else:
        other_lines.append(line)

# This simple logic might be too fragile. Let's just manually re-arrange.
