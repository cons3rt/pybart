#!/bin/bash

# Source the environment
if [ -f /etc/bashrc ] ; then
    . /etc/bashrc
fi
if [ -f /etc/environment ] ; then
    . /etc/environment
fi

# Establish a log file and log tag
logTag="pybart-install"
logDir="/var/log/cons3rt"
logFile="${logDir}/${logTag}-$(date "+%Y%m%d-%H%M%S").log"

######################### GLOBAL VARIABLES #########################

# Git Server Domain Name
gitServerDomainName="github.com"

# pyBART GIT clone URL
pybartGitUrl="https://${gitServerDomainName}/cons3rt/pybart.git"

# Default GIT branch
defaultGitBranch="master"

# Root directory for pyBART src and other files
pybartRoot="/root/.pycons3rt"

# Defines the directory where cons3rt-deploying-cons3rt source code will
# be staged and installed to.
pybartSrcDir="${pybartRoot}/src/pybart"

# Path to the pybart linux install script
pybartInstaller=

####################### END GLOBAL VARIABLES #######################

# Logging functions
function timestamp() { date "+%F %T"; }
function logInfo() { echo -e "$(timestamp) ${logTag} [INFO]: ${1}" >> ${logFile}; }
function logWarn() { echo -e "$(timestamp) ${logTag} [WARN]: ${1}" >> ${logFile}; }
function logErr() { echo -e "$(timestamp) ${logTag} [ERROR]: ${1}" >> ${logFile}; }

function set_deployment_home() {
    # Ensure DEPLOYMENT_HOME exists
    if [ -z "${DEPLOYMENT_HOME}" ] ; then
        logWarn "DEPLOYMENT_HOME is not set, attempting to determine..."
        deploymentDirCount=$(ls /opt/cons3rt-agent/run | grep Deployment | wc -l)
        # Ensure only 1 deployment directory was found
        if [ ${deploymentDirCount} -ne 1 ] ; then
            logErr "Could not determine DEPLOYMENT_HOME"
            return 1
        fi
        # Get the full path to deployment home
        deploymentDir=$(ls /opt/cons3rt-agent/run | grep "Deployment")
        deploymentHome="/opt/cons3rt-agent/run/${deploymentDir}"
        export DEPLOYMENT_HOME="${deploymentHome}"
    else
        deploymentHome="${DEPLOYMENT_HOME}"
    fi
}

function read_deployment_properties() {
    local deploymentPropertiesFile="${DEPLOYMENT_HOME}/deployment-properties.sh"
    if [ ! -f ${deploymentPropertiesFile} ] ; then
        logErr "Deployment properties file not found: ${deploymentPropertiesFile}"
        return 1
    fi
    . ${deploymentPropertiesFile}
    return $?
}

function verify_dns() {
    # Tries to resolve a domain name for 5 minutes
    # Parameters:
    # 1 - Domain Name (e.g. example.com)
    # Returns:
    # 0 - Successfully resolved domain name
    # 1 - Failed to resolve domain name
    local domainName=$1
    local count=0
    while [ ${count} -le 150 ] ; do
        logInfo "Verifying domain name resolution for ${domainName}"
        getent hosts ${domainName}
        if [ $? -ne 0 ] ; then
            logWarn "Could not resolve domain name - ${domainName} - trying again in 2 seconds..."
        else
            logInfo "Successfully resolved domain name: ${domainName}!"
            return 0
        fi
        count=$((${count}+1))
        sleep 2
    done
    logErr "Failed DNS resolution for domain name: ${domainName}"
    return 1
}

function verify_prerequisites() {
    logInfo "Verifying prerequisites are installed..."

    logInfo "Ensuring python is installed..."
    python --version >> ${logFile} 2>&1
	if [ $? -ne 0 ] ; then
        logErr "Python not detected, and is a required dependency"
        return 1
    fi

    logInfo "Ensuring pip is installed..."
    pip --version >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then
        logErr "pip is not installed, this is a required dependency"
        return 2
    fi

    logInfo "Ensuring the pycons3rt package is installed..."
    python -c "import pycons3rt" >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then
        logErr "pycons3rt not detected, this is a required dependency"
        return 3
    fi
    logInfo "Verified prerequisites!"
    return 0
}

function install_pip_packages() {
    logInfo "Installing pip packages..."

    logInfo "Installing the requests package using pip..."
    pip install requests_toolbelt >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "There was a problem installing requests_toolbelt"; return 1; fi

    logInfo "All pip packages installed successfully"
    return 0
}

function git_clone() {
    logInfo "Attempting to git clone the pybart repo..."

    # Verify connectivity to the git repo domain
    verify_dns ${gitServerDomainName}
    if [ $? -ne 0 ] ; then
        logErr "Unable to resolve GIT server domain name: ${gitServerDomainName}"
        return 1
    else
        logInfo "Successfully resolved domain name: ${gitServerDomainName}"
    fi

    # Determine the pybart branch
    pybartBranch="${defaultGitBranch}"
    if [ ! -z "${PYBART_BRANCH}" ] ; then
        logInfo "Found deployment property PYBART_BRANCH: ${PYBART_BRANCH}"
        pybartBranch="${PYBART_BRANCH}"
    else
        logInfo "PYBART_BRANCH deployment property not found, git will clone the ${pybartBranch} branch"
    fi

    # Create the src directory
    logInfo "Creating directory ${pybartSrcDir}..."
    mkdir -p ${pybartSrcDir} >> ${logFile} 2>&1

    logInfo "Ensuring HOME is set..."
    if [ -z "${HOME}" ] ; then
        export HOME="/root"
    fi

    # Git clone the specified branch
    logInfo "Cloning the pyBART GIT repo..."
    for i in {1..10} ; do
        logInfo "Attempting to clone the GIT repo, attempt ${i} of 10..."
        git clone -b ${pybartBranch} --depth 1 ${pybartGitUrl} ${pybartSrcDir}
        result=$?
        logInfo "git clone exited with code: ${result}"
        if [ ${result} -ne 0 ] && [ $i -ge 10 ] ; then
            logErr "Unable to clone git repo after ${i} attempts: ${gitUrl}"
            return 2
        elif [ ${result} -ne 0 ] ; then
            logWarn "Unable to clone git repo, re-trying in 5 seconds: ${gitUrl}"
            sleep 5
        else
            logInfo "Successfully cloned git repo: ${gitUrl}"
            break
        fi
    done

    # Ensure the pybart install script can be found
    pybartInstaller="${pybartSrcDir}/scripts/install.sh"
    if [ ! -f ${pybartInstaller} ] ; then
        logErr "pybart install script not found: ${pybartInstaller}, source code may not have been checked out or staged correctly"
        return 3
    fi
    logInfo "Found file: ${pybartInstaller}, git clone succeeded!"
    return 0
}

function install_pybart() {
    # Install the pybart python project into the system python lib
    logInfo "Attempting to install pybart..."
    ${pybartInstaller} >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then logInfo "pycons3rt install exited with code: ${?}"; return 1; fi
    logInfo "pybart install completed successfully!"
    return 0
}

function main() {
    logInfo "Beginning ${logTag} install..."
    set_deployment_home
    read_deployment_properties
    verify_prerequisites
    if [ $? -ne 0 ]; then logErr "A required prerequisite is not installed"; return 1; fi
    install_pip_packages
    if [ $? -ne 0 ] ; then logErr "There was a problem installing one or more pip packages"; return 2; fi
    git_clone
    if [ $? -ne 0 ] ; then logErr "There was a problem cloning the pybart git repo"; return 3; fi
    install_pybart
    if [ $? -ne 0 ] ; then logErr "There was a problem installing pybart"; return 4; fi
    logInfo "Completed: ${logTag} install script"
    return 0
}

# Set up the log file
mkdir -p ${logDir}
chmod 700 ${logDir}
touch ${logFile}
chmod 644 ${logFile}

main
result=$?
cat ${logFile}

logInfo "Exiting with code ${result} ..."
exit ${result}
