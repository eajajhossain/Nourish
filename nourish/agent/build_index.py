"""Build the Chroma knowledge index.

    python -m nourish.agent.build_index            # dishes + recipes + IFCT PDF
    python -m nourish.agent.build_index --no-pdf   # skip the PDF (faster)
"""
from __future__ import annotations

import sys

from . import vectorstore

if __name__ == "__main__":
    include_pdf = "--no-pdf" not in sys.argv
    print("Building Nourish knowledge index"
          + (" (with IFCT 2017 PDF — takes a few minutes)" if include_pdf else ""))
    vectorstore.build(include_pdf=include_pdf)
