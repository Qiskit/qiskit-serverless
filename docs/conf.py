"""
Sphinx documentation builder
"""

# General options:
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath('../client'))

project = "Quantum serverless"
copyright = "2022"  # pylint: disable=redefined-builtin
author = ""

_rootdir = Path(__file__).parent.parent

# The full version, including alpha/beta/rc tags
release = "0.0.0"
# The short X.Y version
version = "0.0"

extensions = [
    "sphinx.ext.napoleon",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.mathjax",
    "sphinx.ext.viewcode",
    "sphinx.ext.extlinks",
    "jupyter_sphinx",
    "sphinx_autodoc_typehints",
    "reno.sphinxext",
    "nbsphinx",
    "sphinx_copybutton",
]
templates_path = ["_templates"]
numfig = True
numfig_format = {"table": "Table %s"}
language = "en"
pygments_style = "colorful"
add_module_names = False
modindex_common_prefix = ["quantum_serverless_project."]

# html theme options
html_static_path = ["_static"]
# html_logo = "_static/images/logo.png"
html_theme_options = {
    'github_button': True,
    'github_user': 'Qiskit-Extensions',
    'github_repo': 'quantum-serverless',
    'github_type': 'star',
    'github_count': False,
    'extra_nav_links': {
        'Repository': 'https://github.com/Qiskit-Extensions/quantum-serverless',
        'Report issues': 'https://github.com/Qiskit-Extensions/quantum-serverless/issues/new?assignees=&labels=bug&template=bug_report.md'
    }
}

# autodoc/autosummary options
autosummary_generate = True
autosummary_generate_overwrite = False
autoclass_content = "both"

# nbsphinx options (for tutorials)
nbsphinx_timeout = 180
nbsphinx_execute = "never"
nbsphinx_widgets_path = ""
exclude_patterns = ["_build", "**.ipynb_checkpoints"]

