#
# schema.py
#
# Timothy Graefe, Javamata LLC
#

import logging

from arango.exceptions import CollectionCreateError
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models.base import ModelBase
from django.db.backends.arangodb.fields.edges import EdgeField

logger = logging.getLogger('django.db.backends.arangodb')

class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):

    def create_model(self, model: ModelBase):
        name = model._meta.db_table
        logger.debug(f"\nDatabaseSchemaEditor: create_model: {name}")
        super().create_model(model)

        try:
            self.connection.Database.adb.create_collection(name, edge=False)

        except CollectionCreateError:
            logger.debug(f"Collection {name} already exists.")

    def delete_model(self, model):
        name = model._meta.db_table
        logger.debug(f"\nDatabaseSchemaEditor: delete_model: {name}")

        try:
            self.connection.Database.adb.delete_collection(name)

        except CollectionDeleteError:
            logger.debug(f"Collection {name} not found")

    def add_field(self, model, field):
        # In the general case, there is nothing to do for ArangoDB
        # to add a field (unless schema validation is enabled).
        # However, if this is an edge field, then the following actions
        # must be taken:
        """
            1) check to see if a graph with the same name exists, andd 
                create the graph if it does not exist.
            2) create an edge definition structure
            3) add the edge definition to the graph
        """
        logger.debug(f"\nDatabaseSchemaEditor: add_field:")
        super().add_field(model, field)

        if not isinstance(field, EdgeField):
            return

        edge_name = field.remote_field.edge_name
        graph_name = field.remote_field.graph_name

        # This is an EdgeField so further processing is required.
        # field.name - name of the field in parent class
        # field.remote_field.edge_name - name of the edge collection
        # field.remote_field.graph_name - name of the ADB graph
        # field.remote_field.model - the target model class (e.g., '__fake__.ModelB')
        # model - the source model class (e.g., '__fake__.ModelA')
        #
        # The '__fake__' classes hold the DB fields and methods (see the note at
        # bottom of this file).
        ed = {          "edge_collection" : edge_name,
                "from_vertex_collections" : [ field.from_vertex_collection, ],
                  "to_vertex_collections" : [ field.to_vertex_collection, ], }
        edlist = [ ed, ]

        if self.connection.Database.adb.has_graph(graph_name):
            adb_graph = self.connection.Database.adb.graph(graph_name)
            logger.debug(f"Adding edge definition to graph {graph_name}")
            adb_graph.create_edge_definition(
                edge_collection         = edge_name,
                from_vertex_collections = [ field.from_vertex_collection, ],
                to_vertex_collections   = [ field.to_vertex_collection,   ])
        else:
            try:
                adb_graph = self.connection.Database.adb.create_graph(graph_name, edlist)
            except GraphCreateError:
                logger.debug(f"Unable to create graph {graph_name}")
            else:
                logger.debug(f"Created graph {graph_name} with new edge definition")


"""
Fake ModelA info:

:::::  Class definition  :::::

  class ModelA(ModelBase): members=11 methods=47 built-ins=28

  ModelA members:
    DoesNotExist
    MultipleObjectsReturned
    id
    title
    description
    mcount
    objects
    modelb_via_fk
    (3 hidden members)

  ModelA methods:
    DoesNotExist
    MultipleObjectsReturned
    check
    clean
    clean_fields
    date_error_message
    delete
    from_db
    full_clean
    get_deferred_fields
    prepare_database_save
    refresh_from_db
    save
    save_base
    serializable_value
    unique_error_message
    validate_unique
    (30 hidden methods)
    (28 hidden built-ins)
"""

# schema.py
