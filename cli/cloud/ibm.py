import sys
sys.path.append(".")

import click
import os

from text.constants import LINE_DECORATOR, CLOUD_IBM_WELCOME

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(CLOUD_IBM_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

@click.command()
@click.option(
    "--username", prompt=True,
    default=lambda: os.environ.get("USER", "")
)
def username(username):
    click.echo(f"Your IBM Cloud username is: {username}")

def run():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style("IBM CLOUD NOT IMPLEMENTED YET", fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

def ibm():
    welcome()
    run()