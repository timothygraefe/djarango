#
# schema.py
#
# Timothy Graefe, Javamata LLC
#

import logging

from arango.exceptions import CollectionCreateError
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models.base import ModelBase

logger = logging.getLogger('django.db.backends.arangodb')

class DatabaseSchemaEditor(BaseDatabaseSchemaEditor):

    def create_model(self, model: ModelBase):
        name = model._meta.db_table
        logger.debug(f"\nDatabaseSchemaEditor: create_model: {name}")
        super().create_model(model)

        try:
            self.connection.Database.adb.create_collection(name, edge=False)

        except CollectionCreateError:
            logger.debug("Collection {name} already exists.")

    def delete_model(self, model):
        name = model._meta.db_table
        logger.debug("\nDatabaseSchemaEditor: delete_model: {name}")

        try:
            self.connection.Database.adb.delete_collection(name)

        except CollectionDeleteError:
            logger.debug("Collection {name} not found")

# schema.py
