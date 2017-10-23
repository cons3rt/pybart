#!/bin/bash

# Created by Joe Yennaco (9/7/2016)

# Set log commands
logTag="pybart-install"
logInfo="logger -i -s -p local3.info -t ${logTag} -- [INFO] "
logWarn="logger -i -s -p local3.warning -t ${logTag} -- [WARNING] "
logErr="logger -i -s -p local3.err -t ${logTag} -- [ERROR] "

# Get the current timestamp and append to logfile name
TIMESTAMP=$(date "+%Y-%m-%d-%H%M")

${logInfo} "Sourcing /etc/bashrc to get the environment ..."
source /etc/bashrc

######################### GLOBAL VARIABLES #########################

# Git Server Domain Name
gitServerDomainName="git.jackpinetech.com"

# pyBART GIT clone URL
pybartGitUrl="git@${gitServerDomainName}:jackpine/pyBART.git"

# Default GIT branch
defaultGitBranch="develop"

# Root directory for pyBART src and other files
pybartRoot="/root/.pycons3rt"

# Defines the directory where cons3rt-deploying-cons3rt source code will
# be staged and installed to.
pybartSrcDir="${pybartRoot}/src/pyBART"

# Deployment properties filename
deploymentPropsFile="deployment-properties.sh"

# Array to maintain exit codes of RPM install commands
resultSet=();

# Ensure ASSET_DIR exists, if not assume this script exists in ASSET_DIR/scripts
if [ -z "${ASSET_DIR}" ] ; then
    ${logWarn} "ASSET_DIR not found, assuming ASSET_DIR is 1 level above this script ..."
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    ASSET_DIR=${SCRIPT_DIR}/..
fi
mediaDir="${ASSET_DIR}/media"

####################### END GLOBAL VARIABLES #######################

# Executes the passed command, adds the status to the resultSet
# array and return the exit code of the executed command
# Parameters:
# 1 - Command to execute
# Returns:
# Exit code of the command that was executed
function run_and_check_status() {
    "$@"
    local status=$?
    if [ ${status} -ne 0 ] ; then
        ${logErr} "Error executing: $@, exited with code: ${status}"
    else
        ${logInfo} "$@ executed successfully and exited with code: ${status}"
    fi
    resultSet+=("${status}")
    return ${status}
}

# Tries to resolve a domain name for 5 minutes
# Parameters:
# 1 - Domain Name (e.g. example.com)
# Returns:
# 0 - Successfully resolved domain name
# 1 - Failed to resolve domain name
function verify_dns() {
    local domainName=$1
    local count=0
    while [ ${count} -le 150 ] ; do
        ${logInfo} "Verifying domain name resolution for ${domainName}"
        getent hosts ${domainName}
        if [ $? -ne 0 ] ; then
            ${logWarn} "Could not resolve domain name - ${domainName} - trying again in 2 seconds..."
        else
            ${logInfo} "Successfully resolved domain name: ${domainName}!"
            return 0
        fi
        count=$((${count}+1))
        sleep 2
    done
    ${logErr} "Failed DNS resolution for domain name: ${domainName}"
    return 1
}

# Install and verify pyBART prerequisites
function install_prerequisites() {
    ${logInfo} "Checking and installing prerequisites for pyBART..."
    python --version
	if [ $? -ne 0 ] ; then
        ${logErr} "Python not detected, and is a required dependency"
        return 1
    fi

    ${logInfo} "Ensuring the pycons3rt package is installed..."
    python -c "import pycons3rt"
    if [ $? -ne 0 ] ; then
        ${logErr} "pycons3rt not detected, this is a required dependency"
        return 2
    fi

    ${logInfo} "Ensuring pip is installed..."
    pip --version
    if [ $? -ne 0 ] ; then
        ${logErr} "pip is not installed, this is a required dependency"
        return 3
    fi

    ${logInfo} "Installing the requests package using pip..."
    pip install requests==2.10.0
    if [ $? -ne 0 ] ; then
        ${logErr} "Unable to install the Python requests package using pip, this is a required dependency"
        return 4
    fi

    ${logInfo} "Installing the requests package using pip..."
    pip install requests_toolbelt
    if [ $? -ne 0 ] ; then
        ${logErr} "Unable to install the Python requests_toolbelt package using pip, this is a required dependency"
        return 5
    fi

    ${logInfo} "pyBART prerequisites have been installed and verified"
    return 0
}

# Main Install Function
function main() {
    ${logInfo} "Beginning ${logTag} install..."
    ${logInfo} "Timestamp: ${TIMESTAMP}"

    # Ensure DEPLOYMENT_HOME exists
    if [ -z "${DEPLOYMENT_HOME}" ] ; then
        ${logWarn} "DEPLOYMENT_HOME is not set, attempting to determine..."
        deploymentDirCount=$(ls /opt/cons3rt-agent/run | grep Deployment | wc -l)
        # Ensure only 1 deployment directory was found
        if [ ${deploymentDirCount} -ne 1 ] ; then
            ${logErr} "Could not determine DEPLOYMENT_HOME"
            return 1
        fi
        # Get the full path to deployment home
        deploymentDir=$(ls /opt/cons3rt-agent/run | grep Deployment)
        deploymentHome="/opt/cons3rt-agent/run/${deploymentDir}"
    else
        deploymentHome="${DEPLOYMENT_HOME}"
        ${logInfo} "DEPLOYMENT_HOME: ${deploymentHome}"
    fi

    # Ensure the deployment properties file can be found
    deploymentProperties="${deploymentHome}/${deploymentPropsFile}"
    if [ ! -f ${deploymentProperties} ] ; then
        ${logErr} "File not found: ${deploymentProperties}"
        return 2
    else
        ${logInfo} "Found deployment properties file: ${deploymentProperties}"
    fi

    # Source deployment properties
    run_and_check_status source ${deploymentProperties}

    verify_dns ${gitServerDomainName}
    if [ $? -ne 0 ] ; then
        ${logErr} "Unable to resolve GIT server domain name: ${gitServerDomainName}"
        return 3
    else
        ${logInfo} "Successfully resolved domain name: ${gitServerDomainName}"
    fi

    pybartBranch=${defaultGitBranch}
    if [ ! -z "${PYBART_BRANCH}" ] ; then
        ${logInfo} "Found deployment property PYBART_BRANCH: ${PYBART_BRANCH}"
        pybartBranch=${PYBART_BRANCH}
    else
        ${logInfo} "PYBART_BRANCH deployment property not found, git will clone the ${pybartBranch} branch"
    fi

    # Create the src directory
    ${logInfo} "Creating directory ${pybartSrcDir}..."
    run_and_check_status mkdir -p ${pybartSrcDir}

    ${logInfo} "Ensuring HOME is set..."
    if [ -z "${HOME}" ] ; then
        export HOME="/root"
    fi

    ${logInfo} "Adding ${gitServerDomainName} to known_hosts"
    ssh-keyscan ${gitServerDomainName} >> /root/.ssh/known_hosts

    # Git clone the specified branch
    ${logInfo} "Cloning the pyBART GIT repo..."
    for i in {1..10} ; do
        ${logInfo} "Attempting to clone the GIT repo, attempt ${i} of 10..."
        git clone -b ${pybartBranch} --depth 1 ${pybartGitUrl} ${pybartSrcDir}
        result=$?
        ${logInfo} "git clone exited with code: ${result}"
        if [ ${result} -ne 0 ] && [ $i -ge 10 ] ; then
            ${logErr} "Unable to clone git repo after ${i} attempts: ${gitUrl}"
            return 4
        elif [ ${result} -ne 0 ] ; then
            ${logWarn} "Unable to clone git repo, re-trying in 5 seconds: ${gitUrl}"
            sleep 5
        else
            ${logInfo} "Successfully cloned git repo: ${gitUrl}"
            break
        fi
    done

    # Install prerequisites for pyBART
    install_prerequisites
    if [ $? -ne 0 ] ; then
        ${logErr} "There was a problem installing prerequisites for pyBART"
        return 5
    else
        ${logInfo} "Successfully installed pyBART prerequisites"
    fi

    # Ensure the pybart install script can be found
    pybartInstaller="${pybartSrcDir}/scripts/install.sh"
    if [ ! -f ${pybartInstaller} ] ; then
        ${logErr} "pybart install script not found: ${pybartInstaller}, source code may not have been checked out or staged correctly"
        return 6
    else
        ${logInfo} "Found file: ${pybartInstaller}"
    fi

    # Install the pybart python project into the system python lib
    ${logInfo} "Installing the pybart python package..."
    ${pybartInstaller}
    installResult=$?

    # Exit with an error if the checkout did not succeed
    if [ ${installResult} -ne 0 ] ; then
        ${logInfo} "pybart install did not complete successfully and exited with code: ${installResult}"
        return 7
    else
        ${logInfo} "pybart completed successfully!"
    fi

    ${logInfo} "Verifying asset installed successfully ..."
    # Check the results of commands from this script, return error if an error is found
    for resultCheck in "${resultSet[@]}" ; do
        if [ ${resultCheck} -ne 0 ] ; then
            ${logErr} "Non-zero exit code found: ${resultCheck}"
            return 8
        fi
    done
    ${logInfo} "Completed ${logTag} successfully!"
    return 0
}

main
result=$?

${logInfo} "Exiting with code ${result} ..."
exit ${result}
