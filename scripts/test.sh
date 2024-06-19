#!/usr/bin/env bash

SCRIPT_NAME=$(basename $0)
echo "Running ${SCRIPT_NAME}"

#!/usr/bin/env bash

# shellcheck disable=SC2230
if ! which python3; then
  echo "Installing Python 3..."
  yum update -yq && yum install -yq python3-pip
fi

echo ""
python3 --version
echo ""

# shellcheck disable=SC2230
if ! which pip3; then
  echo "Installing pip3..."
  yum update -yq && yum install -yq python3-pip
fi

echo ""
pip3 -V
echo ""

echo "Installing required modules..."
pip3 install flask
pip3 install prometheus_client
pip3 install flasgger
pip3 install ibmcloudenv
pip3 install tox
echo ""

# set -x
echo "Executing unit-tests..."
cd gateway
echo "install dependencies"
pip install -r requirements.txt
pip install -r requirements-dev.txt
echo "lint"
pylint --load-plugins pylint_django --load-plugins pylint_django.checkers.migrations --django-settings-module=main.settings --ignore api.migrations -rn api main
echo "test"
python manage.py test


#python3 -W ignore::ResourceWarning -m unittest discover -s tests -v -p "*.py" > "$WORKSPACE/unit-tests.log" 2>&1

exit_code=$?
status="success"
if [ $exit_code == "0" ]; then
  echo "Unit tests completed OK..."
else
  echo "Error executing unit tests !!!"
  status="failure"
fi
echo ""
cat "$WORKSPACE/unit-tests.log"
echo ""

collect-evidence \
    --tool-type "unittest" \
    --status "$status" \
    --evidence-type "com.ibm.unit_tests" \
    --asset-type "repo" \
    --asset-key "app-repo" \
    --attachment "$WORKSPACE/unit-tests.log"

echo "Saving results..."
save_result test "$WORKSPACE/unit-tests.log"

exit $exit_code
