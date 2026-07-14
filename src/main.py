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
from ollama import generate


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


def compile_latex(tex_path: Path) -> Optional[str]:
    """turns the latex file (*.tex) at tex_path into a PDf

    Args:
        tex_path: the path of the file to convert

    Returns:
        the path of the created pdf file
    """

    path_parent = Path(tex_path).parent
    success: int = os.system(f"cd {path_parent} && latexmk -silent -pdf {tex_path}")
    if not success:
        return None

    return str(Path(tex_path).with_suffix(".pdf"))


@dataclass
class ResumeSection:
    description: str
    output_path: Path
    extra_instructions: Optional[str] = None
    latex_content: str = field(init=False)

    def __post_init__(self):
        if self.extra_instructions:
            self.extra_instructions = "\n\n" + self.extra_instructions.strip()

        with open(self.output_path, "r") as f:
            self.latex_content = f.read()

        if self.extra_instructions:
            self.extra_instructions = (
                "\n\nSpecific instructions for this resume section: "
                + self.extra_instructions.strip()
            )

def prompt_model(prompt: str, ascii_only: bool = True) -> str:
    max_tries = 5
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    for i in range(max_tries):
        if i > 0:
            print(f"Retrying Ollama query {i+1}/{max_tries} in {2 * i} seconds...")
        sleep(2 * i)
        try:
            response = generate(model=model, prompt=prompt)
        except Exception as e:
            print(f"Ollama query failed {i+1}/{max_tries}: {e}")
            continue

        print(f"(context used for Ollama query: {len(response.context or [])} tokens)")
        response_text = response.response
        if not response_text:
            print(f"Ollama query returned empty response {i+1}/{max_tries}")
            continue

        return response_text if not ascii_only else response_text.encode("ascii", errors="ignore").decode("ascii")

    raise Exception("Ollama query returned no response")


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
            print(f"removing old listing file {listing_file}")
            listing_file.unlink()
        print(f"writing new listing to {listing_file}")
        with open(listing_file, "w") as f:
            f.write(get_listing_text(sys.argv[1]))

    if not listing_file.exists():
        raise FileNotFoundError(
            f"listing.txt not found, please provide a job listing URL as the first argument"
        )
    print(f"using existing listing file {listing_file}")
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

    for section in sections:
        other_sections = "\n\n".join(
            f"{s.latex_content}" for s in sections if s != section
        )
        # query = f"""You are a resume reviewing expert. Below is the text from a job posting, and my resume in which we'll focus on the {section.description} section. Please tailor this section to best fit the job.\n\nBe sure to re-phrase, re-order, and re-bold sections appropriately, mirror language from the job posting. Do not bold more than one phrase per bullet point. **Do not use any facts which cannot be directly inferred from the resume already.** Be sure to justify your changes in a comment in the output. **Do not increase the word count, only decrease it.** Note that LaTeX comments are % so text after that doesn't count for the word count. If you add a bulletpoint or un-comment a block you need to remove a simmilarly sized section of text. {section.extra_instructions if section.extra_instructions else ""}\n\n Your response should be valid LaTeX. Any commentary must be in the form of a comment.\n\n===== JOB LISTING =====\n{listing}\n\n===== OTHER SECTIONS OF RESUME =====\n```latex\n{other_sections}\n```\n\n===== RESUME SECTION TO EDIT =====\n```latex\n{section.latex_content}\n```"""
        query = f"""Update the {section.description} section of my resume (below) to best fit the job listing. Also note the other sections of my resume are attached. **CRITICAL: DO NOT LENGTHEN THE RESUME OR INDIVIDUAL LINES AT ALL. UN-COMMENTING (removing %'s at the beginning of lines) LENGTHENS THE RESUME, so any uncomment must be accompanitd by commenting out something else.**{" "+section.extra_instructions if section.extra_instructions else ""} Also do not add any information not already present. Your response should be valid LaTeX. Any commentary must be in the form of a comment. Minimize neglegable changes (adding articles, changing tense, etc.), but re-word and re-structure as needed. Bold (and un-bold) text as needed to highlight important points, no more than 1 bold section per line.\n\n\n===== JOB LISTING =====\n{listing}\n\n\n===== OTHER SECTIONS OF RESUME =====\n```latex\n{other_sections}\n```\n\n\n===== RESUME SECTION TO EDIT =====\n```latex\n{section.latex_content}\n```\n\n\n===== OPTIMIZED RESUME SECTION =====\n"""
        print("=" * 50)
        print(f"generating {section.description} section...")
        print("=" * 50)

        response = prompt_model(query)

        # since the model can't handle any simple instructions
        output = parse_to_valid_latex(response)
        # write response and output to tmp files for comparison
        
        section.latex_content = output

        print(output)

        with open(section.output_path, "w") as f:
            f.write(output)
        with open(section.output_path.with_suffix(".raw"), "w") as f:
            f.write(response)

    compile_latex(working_resume / "resume.tex")

    cover_letter_path = working_resume / "cover_letter.txt"
    prompt = f"""You are a cover letter writing expert. Below is the text from a job posting as well as my resume. I'm the best candidate for this job, and it is your job to convince the hiring managers of that by creating me the perfect cover letter.\n\n**Don't make up any new facts.** Be straight to the point, without being too turse or formal. \n\nYour response should be fully plain text. The cover letter should be no more than 100 words. Write the letter from my perspective (Owen Sullivan). Start with "To whom it may concern," and end with "Best,Owen.".\n\n===== JOB LISTING =====\n{listing}\n\n===== RESUME =====\n```latex\n{''.join(s.latex_content for s in sections)}\n```"""
    cover_letter_text = prompt_model(prompt)

    with open(cover_letter_path, "w") as f:
        f.write(cover_letter_text)

    try:
        os.system(f"pandoc -V geometry:margin=1in -V mainfont=\"Calibri\" --pdf-engine=xelatex {cover_letter_path} -o {cover_letter_path.with_suffix('.pdf')}")
    except Exception as e:
        print(f"failed to convert cover letter to pdf: {e}")



if __name__ == "__main__":
    main()
