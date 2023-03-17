LINE_DECORATOR = '-----------------------------------------'

WELCOME_TEXT = 'Middleware for Quantum Installation CLI'

LOCAL_WELCOME = 'You set installation in a local system'
CLOUD_WELCOME = 'You set installation in a cloud environment'

CLOUD_IBM_WELCOME = 'You are configuring your cluster in an IBM Cloud environment'
CLOUD_MICROSOFT_WELCOME = 'You are configuring your cluster in a Microsoft Azure environment'
CLOUD_AMAZON_WELCOME = 'You are configuring your cluster in an Amazon AWS environment'

LOCAL_DOCKER_WELCOME = 'You are configuring your cluster in local using Docker technology'
LOCAL_TERRAFORM_WELCOME = 'You are configuring your cluster in local using Terraform tool'
LOCAL_HELM_WELCOME = 'You are configuring your cluster in local using Helm tool'

LOCAL_DOCKER_PULLING_IMAGES = 'Pulling docker images...'
LOCAL_DOCKER_INSTALLING_IMAGES = 'Configuring docker pods...'

def link(uri, label=None):
    if label is None: 
        label = uri
    parameters = ''

    # OSC 8 ; params ; URI ST <name> OSC 8 ;; ST 
    escape_mask = '\033]8;{};{}\033\\{}\033]8;;\033\\'

    return escape_mask.format(parameters, uri, label)

LOCAL_DOCKER_RUNNING = """
-----------------------------------------------------------------------------------
Your Middleware for Quantum Docker environment is running in your local system :)
Ray Dashboard: """ + link('http://localhost:8265/') + """
Jupyter Notebook with Tutorial and Guides: """ + link('http://127.0.0.1:8888/') + """
-----------------------------------------------------------------------------------
To stop your docker environment, use the next command: docker compose stop
"""