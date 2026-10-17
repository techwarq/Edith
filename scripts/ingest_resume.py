#!/usr/bin/env python3
"""One-time local ingestion of the resume + writing-style sample used by the
job-application pipeline (edith/tools/growth/job_applications.py).

Run this once (and again whenever the resume/style file changes) so the
pipeline has zero runtime dependency on local files — it reads only from the
DB from then on, same as every other integration in this app. Point
EDITH_DB_PATH at whichever DB the pipeline actually reads from (local dev DB
vs. a shared/hosted one) before running.

Usage:
    python scripts/ingest_resume.py <resume.pdf> [style_sample.txt]
"""

import sys
from pathlib import Path

from pypdf import PdfReader

from edith.config import DB_PATH
from edith.memory.records import career
from edith.memory.storage import sqlite


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    resume_path = Path(sys.argv[1]).expanduser()
    if not resume_path.exists():
        print(f"ERROR: {resume_path} does not exist")
        sys.exit(1)

    style_path = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else None

    conn = sqlite.connect(DB_PATH)
    try:
        resume_text = extract_pdf_text(resume_path)
        if not resume_text:
            print(f"ERROR: extracted no text from {resume_path} — is it a scanned/image PDF?")
            sys.exit(1)
        career.save_resume_text(conn, resume_text, str(resume_path))
        print(f"Saved resume text ({len(resume_text)} chars) from {resume_path} into {DB_PATH}")

        if style_path is not None:
            if not style_path.exists():
                print(f"WARNING: {style_path} does not exist — skipping style sample ingestion")
            else:
                style_text = style_path.read_text().strip()
                if not style_text:
                    print(
                        f"WARNING: {style_path} is empty — the pipeline will fall back to a "
                        "professional-but-personal tone inferred from the resume until you "
                        "paste real writing samples in and re-run this script."
                    )
                else:
                    career.save_style_sample(conn, style_text, str(style_path))
                    print(f"Saved writing-style sample ({len(style_text)} chars) from {style_path}")
        else:
            print("No style sample file given — pipeline will use a fallback tone until one is ingested.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
