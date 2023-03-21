import sys
sys.path.append(".")

import click

from text.constants import LINE_DECORATOR, LOCAL_HELM_WELCOME

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(LOCAL_HELM_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

def run():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style("HELM IN LOCAL NOT IMPLEMENTED YET", fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

def helm():
    welcome()
    run()