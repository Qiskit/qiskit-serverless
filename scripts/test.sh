#!/usr/bin/env bash

SCRIPT_NAME=$(basename $0)
echo "Running ${SCRIPT_NAME}"

yum update -y
yum remove -y python3
yum install -y python3.11
yum install -y python3.11-pip

pip3 install tox

cd gateway
tox -elint > "$WORKSPACE/unit-tests.log" 2>&1 
#tox -epy311

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
