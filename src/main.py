import tempfile
import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from google import genai

from text_extraction import get_listing_text


def compile_latex(tex_path: str) -> Optional[str]:
    """turns the latex file (*.tex) at tex_path into a PDf

    Args:
        tex_path: the path of the file to convert

    Returns:
        the path of the created pdf file
    """
    
    path_parent = Path(tex_path).parent
    success: int = os.system(f'cd {path_parent} && latexmk -pdf {tex_path}')
    if not success:
        return None

    return str(Path(tex_path).with_suffix(".pdf"))



    

def main():
    url = "https://www.symbotic.com/careers/open-positions/R4550/"
    load_dotenv()
    
    client = genai.Client()

    header = "Explain an ideal candidate for the below job listing:\n\n"
    body = get_listing_text(url)

    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=header+body
    )
    print(response.text)

    # compile_latex("c:/Users/Owen/git_projects/resume-customizer/base-resume/resume.tex")

if __name__ == "__main__":
    main()

