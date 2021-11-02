# djarango
ArangoDB Backend Interface for Django

# Installation
```
$ pip install djarango
$ # check install status
$ djarango status
```

# Configure settings.py (example)

```
DATABASES_ARANGO = {
    'default': {
        'ENGINE'       : 'django.db.backends.arangodb',# Backend implementation
        'NAME'         : 'graphdb',                 # DB name
        'HOST'         : 'localhost',               # Single-mode host; 'localhost' is default.
        'PORT'         : '8529',                    # Port 8529 is the default; optional.
        'USER'         : 'someuser',
        'PASSWORD'     : 'somepassword',
        'TIME_ZONE'    : 'UTC',
#       'USE_TZ'       : True,
        'CONN_MAX_AGE' : 60,
        'AUTOCOMMIT'   : True,
        # Arango supports clustered DB
        # If "HOSTS" is provided, it will override "HOST".
#       'HOSTS'     : [ '172.28.0.1', '172.28.0.2', '172.28.0.3', '172.28.0.4', ],
#       'HOST_RESOLVER' : 'rounrobin',      # Options are 'roundrobin' | 'random'
    }
}
```

# Add Edge Fields to a Django model (example)
```
from django.db.backends.arangodb.fields.edges import EdgeField

# Djarango treats every Django model as an ArangoDB collection.
class ModelA(models.Model):
    title           = models.CharField(max_length = 50)
    description     = models.CharField(max_length = 200)
    counta          = models.IntegerField(default = 0)

    # EdgeField creates an edge from ModelA to ModelB
    # ModelA and ModelB are ArangoDB nodes, by default.
    # graph_name specifies the name of the graph that will be created in
    # ArangoDB containing the model (node) collections and edges.
    modelb          = EdgeField('ModelB', graph_name='ABTest')

class ModelB(models.Model):
    title           = models.CharField(max_length = 50)
    description     = models.CharField(max_length = 200)
    countb          = models.IntegerField(default = 0)

    # The EdgeFields are unidirectional.  In order to create a bidirectional
    # edge, there must be an EdgeField in each direction.
    # Specify the same graph_name so that the edges will be in the same graph.
    # Otherwise, a graph name will be auto-generated: 'graph_modelb_modela'
    # and each edge will be in different graphs.
    modela          = EdgeField('ModelA', graph_name='ABTest')
```

# Design Notes
Additional information about design and the edge field implementation is in fields.md
