from __future__ import print_function # Only Python 2.x
import sys
sys.path.append(".")

import click
import subprocess
import parse
import time

from text.constants import LINE_DECORATOR, LOCAL_DOCKER_WELCOME, LOCAL_DOCKER_INSTALLING_IMAGES, LOCAL_DOCKER_PULLING_IMAGES, LOCAL_DOCKER_RUNNING

JUPYTER_NOTEBOOK_BASE_URL = 'http://127.0.0.1:8888/lab'
JUPYTER_NOTEBOOK_TOKEN_OPTION = '?token='

def execute_docker_up():
    urls = {}
    jn_url = JUPYTER_NOTEBOOK_BASE_URL
    jn_url_token = None
    popen = subprocess.Popen(['docker-compose', 'up'], stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ""):
        if JUPYTER_NOTEBOOK_BASE_URL in stdout_line:
            jn_url_token = parse.search(JUPYTER_NOTEBOOK_BASE_URL + JUPYTER_NOTEBOOK_TOKEN_OPTION + '{}\n', stdout_line)
            break
    if jn_url_token is not None:
        jn_url += JUPYTER_NOTEBOOK_TOKEN_OPTION + jn_url_token[0]
    urls['JUPYTER_NOTEBOOK_URL'] = jn_url
    return urls

def replace_msg_middleware_urls(msg, urls):
    final_msg = msg
    for key, url in urls.items():
        final_msg = final_msg.replace(key, url)
    return final_msg

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
    click.echo(click.style(LOCAL_DOCKER_INSTALLING_IMAGES, fg='green'))
    urls = execute_docker_up()
    click.echo(click.style(LOCAL_DOCKER_INSTALLING_IMAGES, fg='green'))
    return urls

def run():
    compose_pull()
    click.echo(click.style(LINE_DECORATOR, fg='blue'))
    urls = compose_up()
    msg_to_show_with_urls = replace_msg_middleware_urls(LOCAL_DOCKER_RUNNING, urls)
    click.clear()
    click.echo(click.style(msg_to_show_with_urls, fg='blue'))

def docker():
    welcome()
    run()