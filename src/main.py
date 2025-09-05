import sys
import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from google import genai
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
import re
from time import sleep


def convert_markdown_to_latex(text: str) -> str:
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

    # Convert # comments to %
    text = re.sub(r"(?<!\\)#(.*)", r"%\1", text)

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


def compile_latex(tex_path: str) -> Optional[str]:
    """turns the latex file (*.tex) at tex_path into a PDf

    Args:
        tex_path: the path of the file to convert

    Returns:
        the path of the created pdf file
    """

    path_parent = Path(tex_path).parent
    success: int = os.system(f"cd {path_parent} && latexmk -pdf {tex_path}")
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

        file_backup: Path = self.output_path.with_suffix(".bak.tex")
        with open(file_backup, "r") as f:
            self.latex_content = f.read()

        if self.extra_instructions:
            self.extra_instructions = "\n\nSpecific instructions for this resume section: " + self.extra_instructions.strip()

def prompt_model(prompt: str, client) -> str:
    max_tries = 5
    response = None
    for i in range(max_tries):
        sleep(2 * i)
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash", contents=prompt
            )
            if response.text:
                break
            else:
                print(f"Gemini query returned empty response {i+1}/{max_tries}")
        except Exception as e:
            print(f"Gemini query failed {i+1}/{max_tries}: {e}")
    if response is None or not response.text:
        raise Exception("Gemini API query returned no response")
    return response.text

def main():
    load_dotenv()
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

    latex_main_path = Path(__file__).parent.parent / "resume" / "resume.tex"
    sections_path: Path = Path(__file__).parent.parent / "resume" / "sections"

    sections: list[ResumeSection] = [
        ResumeSection(
            description="experience",
            extra_instructions="Do not change the order of the experiences.",
            output_path=sections_path / "experience.tex",
        ),
        ResumeSection(
            description="projects",
            extra_instructions="This section should be tailored to highlight the most relevant projects for the job listing. Be sure to switch around which projects are presented to maximize impact, order the projects in order of relevance, and change the descriptions to highlight the most relevant aspects of each project.",
            output_path=sections_path / "projects.tex",
        ),
        ResumeSection(
            description="publications",
            output_path=sections_path / "publications.tex",
        ),
        ResumeSection(
            description="skills",
            output_path=sections_path / "skills.tex",
        ),
        ResumeSection(
            description="education",
            extra_instructions="Be sure to not make up any new information in this section",
            output_path=sections_path / "education.tex",
        ),
        ResumeSection(
            description="summary",
            extra_instructions="Be sure to only include information avaliable in other sections of the resume here",
            output_path=sections_path / "summary.tex",
        ),
    ]

    client = genai.Client()

    for section in sections:
        other_sections = "\n\n".join(
            f"{s.latex_content}" for s in sections if s != section
        )
        query = f"""You are a resume reviewing expert. Below is the text from a job posting. my resume, as well as specifically the {section.description} section of my resume. I'm the best candidate for this job, and it is your job to convince the hiring managers of that by creating me the perfect resume. Please tailor the specified section of my resume to best fit the job.\n\nBe sure to re-phrase, re-order, and re-bold sections appropriately, mirror language from the job posting. Use bolded text sparingly. **Don't make up any new facts.** Be sure to justify your changes in a comment in the output. **Do not increase the word count, only decrease it.**\n\nYour response should be 100% valid LaTeX. Any commentary must be in the form of a comment. {section.extra_instructions if section.extra_instructions else ""}\n\nOver all else, adhere to instructions stated in the section of the resume section if provided.\n\n===== JOB LISTING =====\n{listing}\n\n===== RESUME SECTION TO EDIT =====\n```latex\n{section.latex_content}\n```\n\n===== OTHER SECTIONS OF RESUME =====\n```latex\n{other_sections}\n```"""
        print(query)
        print(f"generating {section.description} section...")
        print("generating response...")

        response = prompt_model(query, client)

        # since the model can't handle any simple instructions
        output = convert_markdown_to_latex(response)
        
        section.latex_content = output

        print(output)

        with open(section.output_path, "w") as f:
            # remove the backticks
            stripped_text = "\n".join(output.splitlines()[1:-1])
            f.write(stripped_text)

    cover_letter_path = Path(__file__).parent.parent / "resume" / "cover_letter.txt"
    cover_letter_text = prompt_model(f"""You are a cover letter writing expert. Below is the text from a job posting as well as my resume. I'm the best candidate for this job, and it is your job to convince the hiring managers of that by creating me the perfect cover letter.\n\n**Don't make up any new facts.** Be straight to the point, without being too turse or formal. \n\nYour response should be fully plain text. The cover letter should be no more than 100 words. Write the letter from my perspective (Owen Sullivan).\n\n===== JOB LISTING =====\n{listing}\n\n===== RESUME =====\n```latex\n{''.join(s.latex_content for s in sections)}\n```""", client)

    with open(cover_letter_path, "w") as f:
        f.write(cover_letter_text)

    # compile_latex(str(latex_main_path))


if __name__ == "__main__":
    main()
