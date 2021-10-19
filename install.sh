#!/bin/sh

PYFILES="db/backends/arangodb/base.py
db/backends/arangodb/client.py
db/backends/arangodb/compiler.py
db/backends/arangodb/creation.py
db/backends/arangodb/features.py
db/backends/arangodb/introspection.py
db/backends/arangodb/operations.py
db/backends/arangodb/schema.py
db/backends/arangodb/fields/edges.py
db/backends/arangodb/fields/edge_descriptors.py"

usage()
{
    echo -e "\n  Usage: install <target directory> [ -install ]"
    exit;
}

if [ -z $1 ] || [ $1 == "-h" ];
then
    usage
fi

DSTDIR=$1
SRCDIR="${HOME}/src/django/"

for PYFILE in ${PYFILES}
do
    cmd="diff ${SRCDIR}/djarango/${PYFILE} ${DSTDIR}/${PYFILE}"
    echo "${cmd}"
    eval "${cmd}"
done

if [ $2 == "-install" ];
then
    for PYFILE in ${PYFILES}
    do
        cmd="cp -v -u ${SRCDIR}/djarango/${PYFILE} ${DSTDIR}/${PYFILE}"
        echo "${cmd}"
        eval "${cmd}"
    done
fi

