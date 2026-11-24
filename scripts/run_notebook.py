import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient

parser = argparse.ArgumentParser()
parser.add_argument("--attention-layout", action="store_true", help="Run the Tiny rank-3 score experiment notebook")
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
source, destination = (
    ("examples/attention_layout.ipynb", "runs/attention-score-layout/adaptation.executed.ipynb")
    if args.attention_layout else ("examples/adaptation.ipynb", "runs/adaptation.executed.ipynb")
)
notebook = nbformat.read(root / source, as_version=4)
NotebookClient(notebook, timeout=180, resources={"metadata": {"path": str(root)}}).execute()
output = root / destination
output.parent.mkdir(parents=True, exist_ok=True)
nbformat.write(notebook, output)
print(output)
