from pathlib import Path

import nbformat
from nbclient import NotebookClient

root = Path(__file__).resolve().parents[1]
notebook = nbformat.read(root / "examples/adaptation.ipynb", as_version=4)
NotebookClient(notebook, timeout=180, resources={"metadata": {"path": str(root)}}).execute()
output = root / "runs/adaptation.executed.ipynb"
nbformat.write(notebook, output)
print(output)
