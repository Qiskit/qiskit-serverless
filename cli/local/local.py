import sys
sys.path.append(".")

import click

from text.constants import LINE_DECORATOR, LOCAL_WELCOME

from .docker import docker
from .terraform import terraform
from .helm import helm

TERRAFORM = 'terraform'
HELM = 'helm'
DOCKER = 'docker'

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(LOCAL_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

@click.command()
@click.option(
    "--tool-type", prompt='Choose your tool technology',
    # type=click.Choice([DOCKER, TERRAFORM, HELM]),
    type=click.Choice([DOCKER]),
    default=DOCKER,
    show_default=DOCKER
)
def tool(tool_type):
    if tool_type == DOCKER:
        docker()
    elif tool_type == TERRAFORM:
        terraform()
    elif tool_type == HELM:
        helm()

def local():
    welcome()
    tool()
   