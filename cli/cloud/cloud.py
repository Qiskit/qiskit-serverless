import sys
sys.path.append(".")

import click

from text.constants import LINE_DECORATOR, CLOUD_WELCOME

from .aws import aws
from .azure import azure
from .ibm import ibm

IBM = 'ibm-cloud'
AWS = 'amazon-aws'
AZURE = 'microsoft-azure'

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(CLOUD_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

@click.command()
@click.option(
    "--cloud-env", prompt='Choose your cloud provider',
    type=click.Choice([IBM, AWS, AZURE]),
    default=IBM,
    show_default=IBM
)
def provider(cloud_env):
    if cloud_env == IBM:
        ibm()
    elif cloud_env == AWS:
        aws()
    elif cloud_env == AZURE:
        azure()

def cloud():
    welcome()
    provider()
