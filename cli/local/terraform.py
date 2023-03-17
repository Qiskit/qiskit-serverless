import sys
sys.path.append(".")

import click

from text.constants import LINE_DECORATOR, LOCAL_TERRAFORM_WELCOME

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(LOCAL_TERRAFORM_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

def terraform():
    welcome()