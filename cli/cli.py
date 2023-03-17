import click

from text.constants import LINE_DECORATOR, WELCOME_TEXT

LOCAL = 'local'
CLOUD = 'cloud'

from local.local import local
from cloud.cloud import cloud

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(WELCOME_TEXT, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

@click.command()
@click.option(
    "--installation-type", prompt='Choose what kind installation you prefer',
    type=click.Choice([LOCAL, CLOUD]),
    default=LOCAL,
    show_default=LOCAL
)
def installation(installation_type):
    if installation_type == LOCAL:
        local()
    elif installation_type == CLOUD:
        cloud()

if __name__ == '__main__':
    welcome()
    installation()
    