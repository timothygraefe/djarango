#!/bin/bash

SYSDIR="${HOME}/.local/lib/python3.8/site-packages/django/"
SRCDIR="${HOME}/src/django/"

usage()
{
    echo -e "$0 [ site ]"
    echo -e "Check for differences with original repo and installed code"
    echo -e "  site - check for differences with site package files"
    echo -e "  [] - do nothing"
    exit
}

PYFILES="db/backends/arangodb/base.py
db/backends/arangodb/client.py
db/backends/arangodb/compiler.py
db/backends/arangodb/creation.py
db/backends/arangodb/features.py
db/backends/arangodb/introspection.py
db/backends/arangodb/operations.py
db/backends/arangodb/schema.py"

if [ -z  $1 ];
then
    usage
fi

mode="unk"
if [ "$1" == "site" ];
then
    mode="site"
else
    usage
fi

if [ ${mode} == "site" ];
then
    for PYFILE in ${PYFILES}
    do
        cmd="diff ${SYSDIR}/${PYFILE} ${SRCDIR}/djarango/${PYFILE}"
        echo "${cmd}"
        eval "${cmd}"
    done
fi

