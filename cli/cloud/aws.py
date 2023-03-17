import sys
sys.path.append(".")

import click
import os

from text.constants import LINE_DECORATOR, CLOUD_AMAZON_WELCOME

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(CLOUD_AMAZON_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

@click.command()
@click.option(
    "--username", prompt=True,
    default=lambda: os.environ.get("USER", "")
)
def username(username):
    click.echo(f"Your Amazon AWS username is: {username}")

def aws():
    welcome()
    username()