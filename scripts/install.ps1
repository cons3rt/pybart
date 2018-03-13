# install.ps1

# The purpose of this script is to install pybart into your local
# python installation

# To automate the install, execute this script like this:
# start /wait powershell -NoLogo -Noninteractive -ExecutionPolicy Bypass -File C:\path\to\install.ps1

$scriptPath = $MyInvocation.MyCommand.Path
$scriptDir = Split-Path $scriptPath
$pybartDir = "$scriptDir\.."
cd $pybartDir
python .\setup.py install
exit $lastexitcode
