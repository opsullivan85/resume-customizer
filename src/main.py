import os
from typing import Optional
from pathlib import Path

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
    compile_latex("c:/Users/Owen/git_projects/resume-customizer/base-resume/resume.tex")

if __name__ == "__main__":
    main()

