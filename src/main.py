import sys
import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
import re
from time import sleep
import shutil
import subprocess
from ollama import generate
from tqdm import tqdm


def parse_to_valid_latex(text: str) -> str:
    """
    Converts Markdown-style formatting to LaTeX:
    - `code` → \texttt{code}
    - **bold** → \textbf{bold}
    - *italic* → \textit{italic}

    Handles non-overlapping, properly nested formatting.
    """
    # Convert inline code: `...` → \texttt{...}
    text = re.sub(r"`([^`]+?)`", r"\\texttt{\1}", text)

    # Convert bold: **...** → \textbf{...}
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)

    # Convert italic: *...* → \textit{...}
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\\textit{\1}", text)

    # For some reason the model is outputting \cveevent instead of \cvevent, so fix that
    text = re.sub(r"(?m)^\\cveevent", r"\\cvevent", text)

    # Convert # comments to %
    text = re.sub(r"(?<!\\)#(.*)", r"%\1", text)

    # escape any & if not already escaped
    text = re.sub(r"(?<!\\)&", r"\\&", text)

    # remove any \comment{...} blocks
    text = re.sub(r"\\comment\{.*?\}", "", text, flags=re.DOTALL)

    # # remove backticks or formatting fences if they exist
    text = re.sub(r"`{2,3}.*?latex\n((?:.*\n)*?)(?:(?:`{3})|(?:\}`{2}))", r"\1", text, flags=re.DOTALL)
    
    text = text.strip()

    return text


def get_listing_text(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0"
    }
    html = requests.get(url, headers=headers).content
    soup = BeautifulSoup(html, features="html.parser")

    # kill all script and style elements
    for script in soup(["script", "style"]):
        script.extract()  # rip it out

    # get text
    text = soup.get_text()

    # break into lines and remove leading and trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # drop blank lines
    text = "\n".join(chunk for chunk in chunks if chunk)

    return text


def compile_latex(tex_path: Path) -> Path:
    """turns the latex file (*.tex) at tex_path into a PDf

    Args:
        tex_path: the path of the file to convert

    Returns:
        the path of the created pdf file
    """

    path_parent = Path(tex_path).parent
    result = subprocess.run(
        ["latexmk", "-silent", "-pdf", tex_path.name],
        cwd=path_parent,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"latexmk failed for {tex_path}: {result.stderr.strip() or result.stdout.strip()}"
        )

    return Path(tex_path).with_suffix(".pdf")


@dataclass
class ResumeSection:
    description: str
    output_path: Path
    extra_instructions: Optional[str] = None
    latex_content: str = field(init=False)

    def __post_init__(self):
        with open(self.output_path, "r") as f:
            self.latex_content = f.read()

def debug_enabled() -> bool:
    return os.getenv("RESUME_CUSTOMIZER_DEBUG", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def debug_print(*args, **kwargs) -> None:
    if debug_enabled():
        print(*args, **kwargs)

def prompt_model(prompt: str, ascii_only: bool = True) -> str:
    max_tries = 5
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    for i in range(max_tries):
        if i > 0:
            debug_print(f"Retrying Ollama query {i+1}/{max_tries} in {2 * i} seconds...")
        sleep(2 * i)
        try:
            response = generate(model=model, prompt=prompt)
        except Exception as e:
            debug_print(f"Ollama query failed {i+1}/{max_tries}: {e}")
            continue

        debug_print(f"(context used for Ollama query: {len(response.context or [])} tokens)")
        response_text = response.response
        if not response_text:
            debug_print(f"Ollama query returned empty response {i+1}/{max_tries}")
            continue

        return response_text if not ascii_only else response_text.encode("ascii", errors="ignore").decode("ascii")

    raise Exception("Ollama query returned no response")


def print_paths_and_assessment(assessment: str, resume_pdf_path: str, cover_letter_pdf_path: str) -> None:
    print()
    print("===== SUMMARY =====")
    print(assessment.strip())
    print()
    print("===== FILE PATHS =====")
    print(f"Resume PDF: {resume_pdf_path}")
    print(f"Cover Letter PDF: {cover_letter_pdf_path}")


def main():
    load_dotenv()

    resume_root = Path(__file__).parent.parent / "resume"
    source_resume = resume_root / "source"
    working_resume = resume_root / "working"

    # Always start from a clean copy of the resume
    if working_resume.exists():
        shutil.rmtree(working_resume)

    shutil.copytree(source_resume, working_resume)

    listing_file = Path(__file__).parent.parent / "listing.txt"
    if len(sys.argv) > 1:
        if not sys.argv[1].startswith("http"):
            raise ValueError(
                "The first argument must be a job listing URL, not a file path."
            )
        if listing_file.exists():
            debug_print(f"removing old listing file {listing_file}")
            listing_file.unlink()
        debug_print(f"writing new listing to {listing_file}")
        with open(listing_file, "w") as f:
            f.write(get_listing_text(sys.argv[1]))

    if not listing_file.exists():
        raise FileNotFoundError(
            f"listing.txt not found, please provide a job listing URL as the first argument"
        )
    debug_print(f"using existing listing file {listing_file}")
    with open(listing_file, "r") as f:
        listing = f.read()
        # remove any non-ascii characters
        # this is important because the model doesn't handle them well
        listing = listing.encode("ascii", errors="ignore").decode("ascii")

    sections_path: Path = working_resume / "sections"

    sections: list[ResumeSection] = [
        ResumeSection(
            description="experience",
            extra_instructions="Do not change the order of the experiences. At most 3 may have bullet points, the rest must be the cvevent only.",
            output_path=sections_path / "experience.tex",
        ),
        ResumeSection(
            description="projects",
            extra_instructions="Re-order the projects in order of relevance. Do not have more than 4 projects listed.",
            output_path=sections_path / "projects.tex",
        ),
        ResumeSection(
            description="research",
            output_path=sections_path / "research.tex",
        ),
        ResumeSection(
            description="skills",
            output_path=sections_path / "skills.tex",
        ),
        ResumeSection(
            description="education",
            # extra_instructions="Be sure to not make up any new information in this section",
            output_path=sections_path / "education.tex",
        ),
        ResumeSection(
            description="summary",
            extra_instructions="Be sure to only include information avaliable in other sections of the resume here",
            output_path=sections_path / "summary.tex",
        ),
    ]

    progress = tqdm(total=len(sections) + 2, desc="progress", unit="step")

    for section in sections:
        progress.set_postfix_str(f"section: {section.description}")
        other_sections = "\n\n".join(
            f"{s.latex_content}" for s in sections if s != section
        )
        query = f"""Update the {section.description} section of my resume (below) to best fit the job listing
Also note the other sections of my resume are attached. **CRITICAL: DO NOT LENGTHEN THE RESUME OR INDIVIDUAL
LINES AT ALL. UN-COMMENTING (removing %'s at the beginning of lines) LENGTHENS THE RESUME, so any uncomment
must be accompanitd by commenting out something else.
**{" "+section.extra_instructions if section.extra_instructions else ""} Also do not add any information not
already present. Your response should be valid LaTeX. Any commentary must be in the form of a comment. Minimize
neglegable changes (adding articles, changing tense, etc.), but re-word and re-structure as needed. Bold (and
un-bold) text as needed to highlight important points, no more than 1 bold section per line.


===== JOB LISTING =====
{listing}


===== OTHER SECTIONS OF RESUME =====
```latex
{other_sections}
```


===== RESUME SECTION TO EDIT =====
```latex
{section.latex_content}
```


===== OPTIMIZED RESUME SECTION =====
"""
        response = prompt_model(query)

        # since the model can't handle any simple instructions
        output = parse_to_valid_latex(response)
        # write response and output to tmp files for comparison
        
        section.latex_content = output

        debug_print(output)

        with open(section.output_path, "w") as f:
            f.write(output)
        with open(section.output_path.with_suffix(".raw"), "w") as f:
            f.write(response)

        progress.update(1)

    try:
        resume_pdf_path = compile_latex(working_resume / "resume.tex")
    except Exception as e:
        print(f"Error occurred while compiling resume: {e}")
        resume_pdf_path = None

    cover_letter_path = working_resume / "cover_letter.txt"
    progress.set_postfix_str("cover letter")
    prompt = f"""You are a cover letter writing expert. Below is the text from a job posting as well as my
resume. I'm the best candidate for this job, and it is your job to convince the hiring managers of that
by creating me the perfect cover letter. **Don't make up any new facts.** Be straight to the point, without
being too turse or formal. 

Your response should be fully plain text. The cover letter should be no more than 100 words. Write the letter
from my perspective (Owen Sullivan). Start with "To whom it may concern," and end with "Best,\\nOwen.".


===== JOB LISTING =====
{listing}


===== RESUME =====
```latex
{'\n'.join(s.latex_content for s in sections)}
```"""
    cover_letter_text = prompt_model(prompt)
    progress.update(1)

    with open(cover_letter_path, "w") as f:
        f.write(cover_letter_text)

    cover_letter_pdf_path = cover_letter_path.with_suffix(".pdf")
    result = subprocess.run(
        [
            "pandoc",
            "-V",
            "geometry:margin=1in",
            "-V",
            "mainfont=Calibri",
            "--pdf-engine=xelatex",
            str(cover_letter_path),
            "-o",
            str(cover_letter_pdf_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        try:
            raise RuntimeError(
                f"pandoc failed for {cover_letter_path}: {result.stderr.strip() or result.stdout.strip()}"
            )
        except Exception as e:
            print(f"Error occurred while compiling cover letter: {e}")
            cover_letter_pdf_path = None

    progress.set_postfix_str("assessment")
    assessment_prompt = f"""**Very briefly** (one paragraph max), does this resume look like a good candidate for our job description?
Be blunt, we have many candidates to consider.

===== JOB LISTING =====
{listing}

===== RESUME =====
```latex
{'\n'.join(s.latex_content for s in sections)}
```

===== COVER LETTER =====
{cover_letter_text}
"""
    assessment_text = prompt_model(assessment_prompt, ascii_only=False)
    progress.update(1)
    progress.close()

    print_paths_and_assessment(
        assessment_text,
        str(resume_pdf_path or "Failed to compile resume PDF"),
        str(cover_letter_pdf_path or "Failed to compile cover letter PDF"),
    )



if __name__ == "__main__":
    main()
