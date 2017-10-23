#!/bin/bash

# The purpose of this script is to install pybart into your local
# python installation

echo "Installing pybart ..."

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd ${SCRIPT_DIR}/..
python ${SCRIPT_DIR}/../setup.py install
result=$?

echo "pybart installation exited with code: ${result}"
exit ${result}
