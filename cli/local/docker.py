import sys
sys.path.append(".")

import click
import subprocess
import time

from text.constants import LINE_DECORATOR, LOCAL_DOCKER_WELCOME, LOCAL_DOCKER_INSTALLING_IMAGES, LOCAL_DOCKER_PULLING_IMAGES, LOCAL_DOCKER_RUNNING

def welcome():
    click.clear()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    click.echo(click.style(LOCAL_DOCKER_WELCOME, fg='green'))
    click.echo(click.style(LINE_DECORATOR, fg='blue'))

def compose_pull():
    cmd_str = 'docker-compose pull'
    click.echo(click.style(LOCAL_DOCKER_PULLING_IMAGES, fg='green'))
    subprocess.run(cmd_str, shell=True)

def compose_up():
    cmd_str = 'docker-compose up'
    click.echo(click.style(LOCAL_DOCKER_INSTALLING_IMAGES, fg='green'))
    subprocess.Popen(cmd_str, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    time.sleep(3)
    click.echo(click.style(LOCAL_DOCKER_INSTALLING_IMAGES, fg='green'))

def run():
    compose_pull()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    compose_up()
    click.clear()
    click.echo(click.style(LOCAL_DOCKER_RUNNING, fg='blue'))

def docker():
    welcome()
    run()